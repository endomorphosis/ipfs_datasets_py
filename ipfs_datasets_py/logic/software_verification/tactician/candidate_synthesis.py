"""Typed candidate lemma/invariant/contract/evidence portfolio (``ProofCandidatePortfolio@1``).

FVT-G033 / FVT-017: combine exact corpus/cache/Hammer retrieval, reviewed
templates, Houdini elimination, SMT cores/interpolation, CHC/PDR/IC3, SyGuS,
legal evidence routing, and learned proposal/ranking providers into *typed
candidate sources*.

Program invariants:

* every candidate records source, provider, provenance, trust, budget, and
  the targeted hole ids;
* autoencoder, Leanstral, SymAI, embeddings, and generic model output remain
  **proposal-only** (authority capped at candidate/advisory; never proof);
* legal-domain obligations **delegate** evidence routing to the existing
  legal tactician compatibility adapter rather than reimplementing search;
* this module owns *composition* of candidate sources — it does not own
  independent caches, provider registries, or proof authority; and
* candidates never claim proof or completion (``CandidateProofStep@1``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, ClassVar, Final, Protocol, runtime_checkable

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    CANDIDATE_PROOF_STEP_SCHEMA,
    AuthorityCeiling,
    CandidateProofStep,
    CandidateStatus,
    HoleKind,
    HoleStatus,
    ProofHole,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
    content_identity,
)

# ---------------------------------------------------------------------------
# Interface and schema constants
# ---------------------------------------------------------------------------

PROOF_CANDIDATE_PORTFOLIO_INTERFACE: Final = "ProofCandidatePortfolio@1"
CANDIDATE_SYNTHESIS_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/candidate-synthesis@1"
)
CANDIDATE_SOURCE_HIT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/candidate-source-hit@1"
)
CANDIDATE_PROPOSAL_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/candidate-proposal@1"
)
PORTFOLIO_RESULT_SCHEMA: Final = (
    "ipfs_datasets_py/logic/software_verification/candidate-portfolio-result@1"
)
PORTFOLIO_ALGORITHM_VERSION: Final = "proof-candidate-portfolio/1.0.0"

# Legal tactician compatibility surface (import-path adapter; no ownership).
LEGAL_TACTICIAN_ADAPTER_ID: Final = "adapter:legal-proof-tactician"
LEGAL_TACTICIAN_MODULE: Final = (
    "ipfs_datasets_py.processors.legal_data.proof_tactician"
)
LEGAL_TACTICIAN_CLASS: Final = "ProofTactician"

DEFAULT_BUDGET: Final = ResourceBounds(
    wall_time_ms=30_000,
    memory_bytes=256 * 1024 * 1024,
    max_steps=64,
    max_depth=16,
    max_nodes=128,
    max_candidates=32,
    model_token_limit=0,
    network_allowed=False,
)

# Provider ids reserved for learned / model proposal sources.
PROPOSAL_ONLY_PROVIDER_PREFIXES: Final[tuple[str, ...]] = (
    "provider:autoencoder",
    "provider:leanstral",
    "provider:symai",
    "provider:embeddings",
    "provider:model",
    "provider:llm",
    "advisor:autoencoder",
    "advisor:leanstral",
    "advisor:symai",
    "advisor:embeddings",
    "advisor:model",
)


class CandidateSynthesisError(ValueError):
    """Raised when candidate synthesis inputs are malformed or unsafe."""


class CandidateSourceKind(StrEnum):
    """Closed set of typed candidate sources (FVT-G033 portfolio)."""

    CORPUS_EXACT = "corpus_exact"
    CACHE_HIT = "cache_hit"
    HAMMER_RETRIEVAL = "hammer_retrieval"
    REVIEWED_TEMPLATE = "reviewed_template"
    HOUDINI_ELIMINATION = "houdini_elimination"
    SMT_UNSAT_CORE = "smt_unsat_core"
    SMT_INTERPOLATION = "smt_interpolation"
    CHC_PDR_IC3 = "chc_pdr_ic3"
    SYGUS = "sygus"
    LEGAL_EVIDENCE_ROUTING = "legal_evidence_routing"
    LEARNED_AUTOENCODER = "learned_autoencoder"
    LEARNED_LEANSTRAL = "learned_leanstral"
    LEARNED_SYMAI = "learned_symai"
    LEARNED_EMBEDDINGS = "learned_embeddings"
    LEARNED_MODEL = "learned_model"


class CandidateTrust(StrEnum):
    """Trust label for a candidate relative to independent validation.

    Trust is descriptive metadata only — it never grants proof authority.
    """

    EXACT_MATCH = "exact_match"
    TEMPLATE = "template"
    SOLVER_DERIVED = "solver_derived"
    SYNTHESIS = "synthesis"
    LEGAL_DELEGATED = "legal_delegated"
    LEARNED_PROPOSAL = "learned_proposal"
    ADVISORY = "advisory"
    UNKNOWN = "unknown"


# Source kinds that must remain proposal-only (authority ≤ candidate).
_PROPOSAL_ONLY_SOURCE_KINDS: Final[frozenset[CandidateSourceKind]] = frozenset(
    {
        CandidateSourceKind.LEARNED_AUTOENCODER,
        CandidateSourceKind.LEARNED_LEANSTRAL,
        CandidateSourceKind.LEARNED_SYMAI,
        CandidateSourceKind.LEARNED_EMBEDDINGS,
        CandidateSourceKind.LEARNED_MODEL,
    }
)

_SOURCE_DEFAULT_TRUST: Final[Mapping[CandidateSourceKind, CandidateTrust]] = {
    CandidateSourceKind.CORPUS_EXACT: CandidateTrust.EXACT_MATCH,
    CandidateSourceKind.CACHE_HIT: CandidateTrust.EXACT_MATCH,
    CandidateSourceKind.HAMMER_RETRIEVAL: CandidateTrust.ADVISORY,
    CandidateSourceKind.REVIEWED_TEMPLATE: CandidateTrust.TEMPLATE,
    CandidateSourceKind.HOUDINI_ELIMINATION: CandidateTrust.SYNTHESIS,
    CandidateSourceKind.SMT_UNSAT_CORE: CandidateTrust.SOLVER_DERIVED,
    CandidateSourceKind.SMT_INTERPOLATION: CandidateTrust.SOLVER_DERIVED,
    CandidateSourceKind.CHC_PDR_IC3: CandidateTrust.SYNTHESIS,
    CandidateSourceKind.SYGUS: CandidateTrust.SYNTHESIS,
    CandidateSourceKind.LEGAL_EVIDENCE_ROUTING: CandidateTrust.LEGAL_DELEGATED,
    CandidateSourceKind.LEARNED_AUTOENCODER: CandidateTrust.LEARNED_PROPOSAL,
    CandidateSourceKind.LEARNED_LEANSTRAL: CandidateTrust.LEARNED_PROPOSAL,
    CandidateSourceKind.LEARNED_SYMAI: CandidateTrust.LEARNED_PROPOSAL,
    CandidateSourceKind.LEARNED_EMBEDDINGS: CandidateTrust.LEARNED_PROPOSAL,
    CandidateSourceKind.LEARNED_MODEL: CandidateTrust.LEARNED_PROPOSAL,
}

_SOURCE_DEFAULT_PROVIDER: Final[Mapping[CandidateSourceKind, str]] = {
    CandidateSourceKind.CORPUS_EXACT: "provider:proof-corpus",
    CandidateSourceKind.CACHE_HIT: "provider:proof-cache",
    CandidateSourceKind.HAMMER_RETRIEVAL: "provider:hammer",
    CandidateSourceKind.REVIEWED_TEMPLATE: "provider:template-library",
    CandidateSourceKind.HOUDINI_ELIMINATION: "provider:houdini",
    CandidateSourceKind.SMT_UNSAT_CORE: "provider:z3",
    CandidateSourceKind.SMT_INTERPOLATION: "provider:cvc5",
    CandidateSourceKind.CHC_PDR_IC3: "provider:spacer",
    CandidateSourceKind.SYGUS: "provider:sygus",
    CandidateSourceKind.LEGAL_EVIDENCE_ROUTING: LEGAL_TACTICIAN_ADAPTER_ID,
    CandidateSourceKind.LEARNED_AUTOENCODER: "provider:autoencoder",
    CandidateSourceKind.LEARNED_LEANSTRAL: "provider:leanstral",
    CandidateSourceKind.LEARNED_SYMAI: "provider:symai",
    CandidateSourceKind.LEARNED_EMBEDDINGS: "provider:embeddings",
    CandidateSourceKind.LEARNED_MODEL: "provider:model",
}

# Rank base (millionths) so deterministic sources sort above learned ones.
_SOURCE_RANK_BASE: Final[Mapping[CandidateSourceKind, int]] = {
    CandidateSourceKind.CORPUS_EXACT: 900_000,
    CandidateSourceKind.CACHE_HIT: 880_000,
    CandidateSourceKind.REVIEWED_TEMPLATE: 800_000,
    CandidateSourceKind.SMT_UNSAT_CORE: 750_000,
    CandidateSourceKind.SMT_INTERPOLATION: 740_000,
    CandidateSourceKind.HOUDINI_ELIMINATION: 700_000,
    CandidateSourceKind.CHC_PDR_IC3: 680_000,
    CandidateSourceKind.SYGUS: 660_000,
    CandidateSourceKind.HAMMER_RETRIEVAL: 650_000,
    CandidateSourceKind.LEGAL_EVIDENCE_ROUTING: 600_000,
    CandidateSourceKind.LEARNED_AUTOENCODER: 400_000,
    CandidateSourceKind.LEARNED_LEANSTRAL: 380_000,
    CandidateSourceKind.LEARNED_SYMAI: 360_000,
    CandidateSourceKind.LEARNED_EMBEDDINGS: 340_000,
    CandidateSourceKind.LEARNED_MODEL: 300_000,
}

# Hole kinds that route through the legal evidence adapter by default.
_LEGAL_HOLE_KINDS: Final[frozenset[HoleKind]] = frozenset(
    {
        HoleKind.MISSING_EVIDENCE,
        HoleKind.MISSING_SOURCE_FACT,
    }
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(
    value: object,
    label: str,
    *,
    optional: bool = False,
    maximum: int = 4096,
) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str):
        raise CandidateSynthesisError(f"{label} must be a string")
    text = value.strip()
    if "\x00" in text:
        raise CandidateSynthesisError(f"{label} must not contain NUL")
    if not optional and not text:
        raise CandidateSynthesisError(f"{label} is required")
    if len(text) > maximum:
        raise CandidateSynthesisError(
            f"{label} exceeds maximum length of {maximum}"
        )
    return text


def _enum(value: object, enum_type: type[StrEnum], label: str) -> Any:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value.strip())
        except ValueError as error:
            allowed = ", ".join(item.value for item in enum_type)
            raise CandidateSynthesisError(
                f"{label} must be one of: {allowed}"
            ) from error
    raise CandidateSynthesisError(f"{label} must be a {enum_type.__name__}")


def _string_tuple(
    values: Sequence[str] | None,
    label: str,
    *,
    preserve_order: bool = True,
    required: bool = False,
) -> tuple[str, ...]:
    if values is None:
        items: tuple[str, ...] = ()
    elif isinstance(values, str):
        items = (_text(values, label, maximum=512),)
    elif isinstance(values, Sequence) and not isinstance(
        values, (bytes, bytearray, memoryview)
    ):
        items = tuple(
            _text(item, f"{label}[{index}]", maximum=512)
            for index, item in enumerate(values)
        )
    else:
        raise CandidateSynthesisError(f"{label} must be a sequence of strings")
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    if not preserve_order:
        result = sorted(result)
    if required and not result:
        raise CandidateSynthesisError(f"{label} must not be empty")
    return tuple(result)


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CandidateSynthesisError(f"{label} must be a non-negative integer")
    return value


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise CandidateSynthesisError(f"{label} must be a boolean")
    return value


def _mapping(value: object, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CandidateSynthesisError(f"{label} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise CandidateSynthesisError(f"{label} keys must be strings")
    return {str(k): value[k] for k in sorted(value)}


def _source_binding(value: object, label: str = "source") -> SourceSpanBinding:
    if isinstance(value, SourceSpanBinding):
        return value
    if isinstance(value, Mapping):
        try:
            return SourceSpanBinding.from_dict(value)
        except TacticianContractError as error:
            raise CandidateSynthesisError(f"{label}: {error}") from error
    raise CandidateSynthesisError(f"{label} must be a SourceSpanBinding")


def _bounds(value: object, label: str = "budget") -> ResourceBounds:
    if value is None:
        return DEFAULT_BUDGET
    if isinstance(value, ResourceBounds):
        return value
    if isinstance(value, Mapping):
        try:
            return ResourceBounds.from_dict(value)
        except TacticianContractError as error:
            raise CandidateSynthesisError(f"{label}: {error}") from error
    raise CandidateSynthesisError(f"{label} must be a ResourceBounds")


def _proof_hole(value: object, label: str = "hole") -> ProofHole:
    if isinstance(value, ProofHole):
        return value
    if isinstance(value, Mapping):
        try:
            return ProofHole.from_dict(value)
        except TacticianContractError as error:
            raise CandidateSynthesisError(f"{label}: {error}") from error
    raise CandidateSynthesisError(f"{label} must be a ProofHole")


def is_proposal_only_source(kind: CandidateSourceKind | str) -> bool:
    """True when the source is learned/model and must stay proposal-only."""

    resolved = _enum(kind, CandidateSourceKind, "kind")
    return resolved in _PROPOSAL_ONLY_SOURCE_KINDS


def is_proposal_only_provider(provider_id: str) -> bool:
    """True when a provider id is reserved for proposal-only learned sources."""

    text = _text(provider_id, "provider_id", maximum=256).lower()
    return any(text == prefix or text.startswith(prefix + ":") or text.startswith(prefix + "/")
               for prefix in PROPOSAL_ONLY_PROVIDER_PREFIXES) or text in {
        p.lower() for p in PROPOSAL_ONLY_PROVIDER_PREFIXES
    }


def is_legal_hole(hole: ProofHole) -> bool:
    """True when a hole should route through legal evidence delegation."""

    if hole.kind in _LEGAL_HOLE_KINDS:
        return True
    markers = (
        "legal",
        "docket",
        "statute",
        "regulation",
        "authority",
        "evidence_routing",
    )
    haystack = " ".join(
        (
            hole.reason,
            hole.statement,
            hole.kind.value,
            " ".join(hole.provider_ids),
        )
    ).lower()
    return any(marker in haystack for marker in markers)


def _stable_candidate_id(*parts: str) -> str:
    digest = hashlib.sha256(
        "|".join(parts).encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    return f"candidate:{parts[0]}:{digest}"


def _cap_authority_for_source(
    kind: CandidateSourceKind,
    authority: AuthorityCeiling,
) -> AuthorityCeiling:
    """Enforce proposal-only authority ceiling for learned sources."""

    if kind in _PROPOSAL_ONLY_SOURCE_KINDS:
        if authority not in {
            AuthorityCeiling.NONE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.CANDIDATE,
        }:
            return AuthorityCeiling.CANDIDATE
    if authority not in {
        AuthorityCeiling.NONE,
        AuthorityCeiling.ADVISORY,
        AuthorityCeiling.CANDIDATE,
    }:
        # Portfolio candidates never elevate past candidate; validation promotes.
        return AuthorityCeiling.CANDIDATE
    return authority


# ---------------------------------------------------------------------------
# Source hits and proposals
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateSourceHit:
    """One raw hit from a typed candidate source (pre-composition).

    Adapters that wrap corpus, cache, Hammer, solvers, templates, legal
    routing, or learned providers emit hits; the portfolio normalizes them
    into :class:`CandidateProposal` values.
    """

    SCHEMA: ClassVar[str] = CANDIDATE_SOURCE_HIT_SCHEMA

    source_kind: CandidateSourceKind
    hole_id: str
    statement: str
    provider_id: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)
    trust: CandidateTrust | None = None
    budget: ResourceBounds | None = None
    source: SourceSpanBinding = field(default_factory=SourceSpanBinding)
    evidence_ids: tuple[str, ...] = ()
    new_assumption_ids: tuple[str, ...] = ()
    rank_score_millionths: int = 0
    kind: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    proposal_only: bool | None = None
    delegated_to: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_kind",
            _enum(self.source_kind, CandidateSourceKind, "source_kind"),
        )
        object.__setattr__(
            self, "hole_id", _text(self.hole_id, "hole_id", maximum=256)
        )
        object.__setattr__(
            self, "statement", _text(self.statement, "statement", maximum=8192)
        )
        default_provider = _SOURCE_DEFAULT_PROVIDER[self.source_kind]
        provider = _text(
            self.provider_id or default_provider,
            "provider_id",
            maximum=256,
        )
        object.__setattr__(self, "provider_id", provider)
        object.__setattr__(
            self, "provenance", _mapping(self.provenance, "provenance")
        )
        trust = self.trust
        if trust is None:
            trust = _SOURCE_DEFAULT_TRUST[self.source_kind]
        else:
            trust = _enum(trust, CandidateTrust, "trust")
        object.__setattr__(self, "trust", trust)
        object.__setattr__(self, "budget", _bounds(self.budget, "budget"))
        object.__setattr__(self, "source", _source_binding(self.source, "source"))
        object.__setattr__(
            self,
            "evidence_ids",
            _string_tuple(self.evidence_ids, "evidence_ids"),
        )
        object.__setattr__(
            self,
            "new_assumption_ids",
            _string_tuple(self.new_assumption_ids, "new_assumption_ids"),
        )
        base = _SOURCE_RANK_BASE.get(self.source_kind, 100_000)
        score = (
            self.rank_score_millionths
            if self.rank_score_millionths
            else base
        )
        object.__setattr__(
            self,
            "rank_score_millionths",
            _nonnegative_int(score, "rank_score_millionths"),
        )
        object.__setattr__(
            self,
            "kind",
            _text(
                self.kind or self.source_kind.value,
                "kind",
                maximum=128,
            ),
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        proposal_only = self.proposal_only
        if proposal_only is None:
            proposal_only = is_proposal_only_source(self.source_kind)
        else:
            proposal_only = _bool(proposal_only, "proposal_only")
        if is_proposal_only_source(self.source_kind) and not proposal_only:
            raise CandidateSynthesisError(
                f"{self.source_kind.value} hits must remain proposal-only"
            )
        object.__setattr__(self, "proposal_only", proposal_only)
        delegated = _text(
            self.delegated_to, "delegated_to", optional=True, maximum=256
        )
        if (
            self.source_kind is CandidateSourceKind.LEGAL_EVIDENCE_ROUTING
            and not delegated
        ):
            delegated = LEGAL_TACTICIAN_ADAPTER_ID
        object.__setattr__(self, "delegated_to", delegated)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "source_kind": self.source_kind.value,
            "hole_id": self.hole_id,
            "statement": self.statement,
            "provider_id": self.provider_id,
            "provenance": dict(self.provenance),
            "trust": self.trust.value if self.trust is not None else CandidateTrust.UNKNOWN.value,
            "budget": self.budget.to_dict() if self.budget is not None else {},
            "source": self.source.to_dict(),
            "evidence_ids": list(self.evidence_ids),
            "new_assumption_ids": list(self.new_assumption_ids),
            "rank_score_millionths": self.rank_score_millionths,
            "kind": self.kind,
            "metadata": dict(self.metadata),
            "proposal_only": bool(self.proposal_only),
            "delegated_to": self.delegated_to,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CandidateSourceHit":
        if not isinstance(payload, Mapping):
            raise CandidateSynthesisError("source hit payload must be an object")
        budget_raw = payload.get("budget")
        return cls(
            source_kind=payload.get("source_kind", CandidateSourceKind.REVIEWED_TEMPLATE),
            hole_id=payload.get("hole_id", ""),
            statement=payload.get("statement", ""),
            provider_id=payload.get("provider_id", ""),
            provenance=payload.get("provenance") or {},
            trust=payload.get("trust"),
            budget=(
                ResourceBounds.from_dict(budget_raw)
                if isinstance(budget_raw, Mapping)
                else budget_raw
            ),
            source=payload.get("source") or {},
            evidence_ids=tuple(payload.get("evidence_ids") or ()),
            new_assumption_ids=tuple(payload.get("new_assumption_ids") or ()),
            rank_score_millionths=int(payload.get("rank_score_millionths") or 0),
            kind=payload.get("kind", ""),
            metadata=payload.get("metadata") or {},
            proposal_only=payload.get("proposal_only"),
            delegated_to=payload.get("delegated_to", ""),
        )


@dataclass(frozen=True, slots=True)
class CandidateProposal:
    """Fully annotated portfolio candidate targeting one or more holes.

    Acceptance: records source/provider/provenance/trust/budget and targeted
    holes; never claims proof or completion.
    """

    SCHEMA: ClassVar[str] = CANDIDATE_PROPOSAL_SCHEMA

    candidate_id: str
    source_kind: CandidateSourceKind
    provider_id: str
    provenance: Mapping[str, Any]
    trust: CandidateTrust
    budget: ResourceBounds
    targeted_hole_ids: tuple[str, ...]
    step: CandidateProofStep
    proposal_only: bool = False
    delegated_to: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _text(self.candidate_id, "candidate_id", maximum=256),
        )
        object.__setattr__(
            self,
            "source_kind",
            _enum(self.source_kind, CandidateSourceKind, "source_kind"),
        )
        object.__setattr__(
            self,
            "provider_id",
            _text(self.provider_id, "provider_id", maximum=256),
        )
        object.__setattr__(
            self, "provenance", _mapping(self.provenance, "provenance")
        )
        object.__setattr__(
            self, "trust", _enum(self.trust, CandidateTrust, "trust")
        )
        object.__setattr__(self, "budget", _bounds(self.budget, "budget"))
        holes = _string_tuple(
            self.targeted_hole_ids, "targeted_hole_ids", required=True
        )
        object.__setattr__(self, "targeted_hole_ids", holes)
        if not isinstance(self.step, CandidateProofStep):
            if isinstance(self.step, Mapping):
                try:
                    step = CandidateProofStep.from_dict(self.step)
                except TacticianContractError as error:
                    raise CandidateSynthesisError(
                        f"step: {error}"
                    ) from error
                object.__setattr__(self, "step", step)
            else:
                raise CandidateSynthesisError(
                    "step must be a CandidateProofStep"
                )
        if self.step.proof_claimed or self.step.completion_claimed:
            raise CandidateSynthesisError(
                "CandidateProposal cannot claim proof or completion"
            )
        if self.step.hole_id not in holes:
            raise CandidateSynthesisError(
                "step.hole_id must be listed in targeted_hole_ids"
            )
        proposal_only = _bool(self.proposal_only, "proposal_only")
        if is_proposal_only_source(self.source_kind) and not proposal_only:
            raise CandidateSynthesisError(
                f"{self.source_kind.value} proposals must remain proposal-only"
            )
        if proposal_only and self.step.authority not in {
            AuthorityCeiling.NONE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.CANDIDATE,
        }:
            raise CandidateSynthesisError(
                "proposal-only candidates cannot exceed candidate authority"
            )
        object.__setattr__(self, "proposal_only", proposal_only)
        object.__setattr__(
            self,
            "delegated_to",
            _text(self.delegated_to, "delegated_to", optional=True, maximum=256),
        )
        if (
            self.source_kind is CandidateSourceKind.LEGAL_EVIDENCE_ROUTING
            and not self.delegated_to
        ):
            raise CandidateSynthesisError(
                "legal evidence candidates must record delegated_to adapter"
            )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "candidate_id": self.candidate_id,
            "source_kind": self.source_kind.value,
            "provider_id": self.provider_id,
            "provenance": dict(self.provenance),
            "trust": self.trust.value,
            "budget": self.budget.to_dict(),
            "targeted_hole_ids": list(self.targeted_hole_ids),
            "step": self.step.to_dict(),
            "proposal_only": self.proposal_only,
            "delegated_to": self.delegated_to,
            "metadata": dict(self.metadata),
            "proof_claimed": False,
            "completion_claimed": False,
        }

    def to_record(self) -> dict[str, Any]:
        return {**self.to_dict(), "content_id": self.content_id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CandidateProposal":
        if not isinstance(payload, Mapping):
            raise CandidateSynthesisError("proposal payload must be an object")
        if payload.get("proof_claimed") is True or payload.get(
            "completion_claimed"
        ) is True:
            raise CandidateSynthesisError(
                "CandidateProposal cannot claim proof or completion"
            )
        budget_raw = payload.get("budget")
        step_raw = payload.get("step") or {}
        return cls(
            candidate_id=payload.get("candidate_id", ""),
            source_kind=payload.get(
                "source_kind", CandidateSourceKind.REVIEWED_TEMPLATE
            ),
            provider_id=payload.get("provider_id", ""),
            provenance=payload.get("provenance") or {},
            trust=payload.get("trust", CandidateTrust.UNKNOWN),
            budget=(
                ResourceBounds.from_dict(budget_raw)
                if isinstance(budget_raw, Mapping)
                else budget_raw if budget_raw is not None else DEFAULT_BUDGET
            ),
            targeted_hole_ids=tuple(payload.get("targeted_hole_ids") or ()),
            step=(
                CandidateProofStep.from_dict(step_raw)
                if isinstance(step_raw, Mapping)
                else step_raw
            ),
            proposal_only=bool(payload.get("proposal_only", False)),
            delegated_to=payload.get("delegated_to", ""),
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class CandidatePortfolioResult:
    """Deterministic result of portfolio synthesis over a hole set."""

    SCHEMA: ClassVar[str] = PORTFOLIO_RESULT_SCHEMA
    INTERFACE: ClassVar[str] = PROOF_CANDIDATE_PORTFOLIO_INTERFACE

    portfolio_id: str
    formal_goal_id: str
    proposals: tuple[CandidateProposal, ...]
    targeted_hole_ids: tuple[str, ...]
    source_kinds_used: tuple[str, ...]
    proposal_only_candidate_ids: tuple[str, ...]
    legal_delegated_candidate_ids: tuple[str, ...]
    algorithm_version: str = PORTFOLIO_ALGORITHM_VERSION
    budget: ResourceBounds = field(default_factory=lambda: DEFAULT_BUDGET)
    proof_claimed: bool = False
    completion_claimed: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "portfolio_id",
            _text(self.portfolio_id, "portfolio_id", maximum=256),
        )
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(
                self.formal_goal_id,
                "formal_goal_id",
                optional=True,
                maximum=256,
            ),
        )
        normalized: list[CandidateProposal] = []
        for index, item in enumerate(self.proposals):
            if isinstance(item, Mapping):
                item = CandidateProposal.from_dict(item)
            elif not isinstance(item, CandidateProposal):
                raise CandidateSynthesisError(
                    f"proposals[{index}] must be a CandidateProposal"
                )
            if item.step.proof_claimed or item.step.completion_claimed:
                raise CandidateSynthesisError(
                    "portfolio proposals cannot claim proof or completion"
                )
            normalized.append(item)
        object.__setattr__(self, "proposals", tuple(normalized))
        object.__setattr__(
            self,
            "targeted_hole_ids",
            _string_tuple(self.targeted_hole_ids, "targeted_hole_ids"),
        )
        object.__setattr__(
            self,
            "source_kinds_used",
            _string_tuple(self.source_kinds_used, "source_kinds_used"),
        )
        object.__setattr__(
            self,
            "proposal_only_candidate_ids",
            _string_tuple(
                self.proposal_only_candidate_ids, "proposal_only_candidate_ids"
            ),
        )
        object.__setattr__(
            self,
            "legal_delegated_candidate_ids",
            _string_tuple(
                self.legal_delegated_candidate_ids,
                "legal_delegated_candidate_ids",
            ),
        )
        object.__setattr__(
            self,
            "algorithm_version",
            _text(self.algorithm_version, "algorithm_version", maximum=128),
        )
        object.__setattr__(self, "budget", _bounds(self.budget, "budget"))
        if self.proof_claimed or self.completion_claimed:
            raise CandidateSynthesisError(
                "CandidatePortfolioResult cannot claim proof or completion"
            )
        object.__setattr__(self, "proof_claimed", False)
        object.__setattr__(self, "completion_claimed", False)
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    @property
    def content_id(self) -> str:
        return content_identity(self.to_dict())

    @property
    def candidate_steps(self) -> tuple[CandidateProofStep, ...]:
        return tuple(item.step for item in self.proposals)

    def proposals_for_hole(self, hole_id: str) -> tuple[CandidateProposal, ...]:
        return tuple(
            item for item in self.proposals if hole_id in item.targeted_hole_ids
        )

    def proposals_of_source(
        self, kind: CandidateSourceKind | str
    ) -> tuple[CandidateProposal, ...]:
        resolved = _enum(kind, CandidateSourceKind, "kind")
        return tuple(
            item for item in self.proposals if item.source_kind is resolved
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "portfolio_id": self.portfolio_id,
            "formal_goal_id": self.formal_goal_id,
            "proposals": [item.to_dict() for item in self.proposals],
            "targeted_hole_ids": list(self.targeted_hole_ids),
            "source_kinds_used": list(self.source_kinds_used),
            "proposal_only_candidate_ids": list(
                self.proposal_only_candidate_ids
            ),
            "legal_delegated_candidate_ids": list(
                self.legal_delegated_candidate_ids
            ),
            "algorithm_version": self.algorithm_version,
            "budget": self.budget.to_dict(),
            "proof_claimed": False,
            "completion_claimed": False,
            "metadata": dict(self.metadata),
        }

    def to_record(self) -> dict[str, Any]:
        return {**self.to_dict(), "content_id": self.content_id}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CandidatePortfolioResult":
        if not isinstance(payload, Mapping):
            raise CandidateSynthesisError("portfolio result payload must be an object")
        if payload.get("proof_claimed") is True or payload.get(
            "completion_claimed"
        ) is True:
            raise CandidateSynthesisError(
                "CandidatePortfolioResult cannot claim proof or completion"
            )
        budget_raw = payload.get("budget")
        return cls(
            portfolio_id=payload.get("portfolio_id", ""),
            formal_goal_id=payload.get("formal_goal_id", ""),
            proposals=tuple(payload.get("proposals") or ()),
            targeted_hole_ids=tuple(payload.get("targeted_hole_ids") or ()),
            source_kinds_used=tuple(payload.get("source_kinds_used") or ()),
            proposal_only_candidate_ids=tuple(
                payload.get("proposal_only_candidate_ids") or ()
            ),
            legal_delegated_candidate_ids=tuple(
                payload.get("legal_delegated_candidate_ids") or ()
            ),
            algorithm_version=payload.get(
                "algorithm_version", PORTFOLIO_ALGORITHM_VERSION
            ),
            budget=(
                ResourceBounds.from_dict(budget_raw)
                if isinstance(budget_raw, Mapping)
                else budget_raw if budget_raw is not None else DEFAULT_BUDGET
            ),
            proof_claimed=False,
            completion_claimed=False,
            metadata=payload.get("metadata") or {},
        )


# ---------------------------------------------------------------------------
# Source adapters (composition only — no owned caches / registries)
# ---------------------------------------------------------------------------


@runtime_checkable
class CandidateSourceAdapter(Protocol):
    """Protocol for injected candidate sources (corpus, cache, solvers, …)."""

    source_kind: CandidateSourceKind

    def propose(
        self,
        hole: ProofHole,
        *,
        budget: ResourceBounds,
    ) -> Sequence[CandidateSourceHit]:
        """Return zero or more hits for ``hole`` within ``budget``."""


@dataclass(frozen=True, slots=True)
class StaticCandidateSource:
    """Deterministic injected hit list keyed by hole id (test / fixture adapter)."""

    source_kind: CandidateSourceKind
    hits_by_hole: Mapping[str, Sequence[CandidateSourceHit | Mapping[str, Any]]] = (
        field(default_factory=dict)
    )
    default_provider_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_kind",
            _enum(self.source_kind, CandidateSourceKind, "source_kind"),
        )
        if not isinstance(self.hits_by_hole, Mapping):
            raise CandidateSynthesisError("hits_by_hole must be a mapping")
        normalized: dict[str, tuple[CandidateSourceHit, ...]] = {}
        for hole_id, hits in self.hits_by_hole.items():
            key = _text(hole_id, "hits_by_hole key", maximum=256)
            items: list[CandidateSourceHit] = []
            for index, hit in enumerate(hits or ()):
                if isinstance(hit, Mapping):
                    payload = {
                        "source_kind": self.source_kind.value,
                        "hole_id": key,
                        **dict(hit),
                    }
                    if not payload.get("provider_id") and self.default_provider_id:
                        payload["provider_id"] = self.default_provider_id
                    items.append(CandidateSourceHit.from_dict(payload))
                elif isinstance(hit, CandidateSourceHit):
                    if hit.hole_id != key:
                        items.append(
                            replace(hit, hole_id=key, source_kind=self.source_kind)
                        )
                    else:
                        items.append(hit)
                else:
                    raise CandidateSynthesisError(
                        f"hits_by_hole[{key!r}][{index}] must be a CandidateSourceHit"
                    )
            normalized[key] = tuple(items)
        object.__setattr__(self, "hits_by_hole", normalized)
        object.__setattr__(
            self,
            "default_provider_id",
            _text(
                self.default_provider_id,
                "default_provider_id",
                optional=True,
                maximum=256,
            ),
        )

    def propose(
        self,
        hole: ProofHole,
        *,
        budget: ResourceBounds,
    ) -> Sequence[CandidateSourceHit]:
        del budget  # static adapter is budget-agnostic
        return self.hits_by_hole.get(hole.hole_id, ())


@dataclass(frozen=True, slots=True)
class LegalEvidenceRoutingAdapter:
    """Compatibility adapter that *delegates* legal evidence routing.

    Does not reimplement docket/index search. Emits candidates that record
    ``delegated_to`` = legal tactician adapter id and optional plan hints
    produced by an injected callable mirroring
    ``processors.legal_data.proof_tactician.ProofTactician``.
    """

    source_kind: CandidateSourceKind = CandidateSourceKind.LEGAL_EVIDENCE_ROUTING
    adapter_id: str = LEGAL_TACTICIAN_ADAPTER_ID
    module_path: str = LEGAL_TACTICIAN_MODULE
    class_name: str = LEGAL_TACTICIAN_CLASS
    plan_builder: Callable[[ProofHole], Mapping[str, Any]] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_kind",
            _enum(self.source_kind, CandidateSourceKind, "source_kind"),
        )
        if self.source_kind is not CandidateSourceKind.LEGAL_EVIDENCE_ROUTING:
            raise CandidateSynthesisError(
                "LegalEvidenceRoutingAdapter source_kind must be legal_evidence_routing"
            )
        object.__setattr__(
            self,
            "adapter_id",
            _text(self.adapter_id, "adapter_id", maximum=256),
        )
        object.__setattr__(
            self,
            "module_path",
            _text(self.module_path, "module_path", maximum=512),
        )
        object.__setattr__(
            self,
            "class_name",
            _text(self.class_name, "class_name", maximum=128),
        )

    def propose(
        self,
        hole: ProofHole,
        *,
        budget: ResourceBounds,
    ) -> Sequence[CandidateSourceHit]:
        if not is_legal_hole(hole):
            return ()
        plan: Mapping[str, Any] = {}
        if self.plan_builder is not None:
            built = self.plan_builder(hole)
            if not isinstance(built, Mapping):
                raise CandidateSynthesisError(
                    "legal plan_builder must return a mapping"
                )
            plan = dict(built)
        statement = (
            f"Delegate evidence routing for {hole.hole_id} to "
            f"{self.adapter_id} ({self.module_path}.{self.class_name})"
        )
        route = plan.get("recommended_route") or (
            "local_docket_documents",
            "local_bm25_index",
            "authority_list",
            "legal_dataset_api",
        )
        if isinstance(route, str):
            route_list = [route]
        else:
            route_list = [str(item) for item in route]
        provenance = {
            "adapter_id": self.adapter_id,
            "module": self.module_path,
            "class": self.class_name,
            "delegation": "legal_evidence_routing",
            "recommended_route": route_list,
            "plan_id": str(plan.get("plan_id") or f"legal-plan:{hole.hole_id}"),
        }
        if plan.get("search_stages"):
            provenance["search_stages"] = plan["search_stages"]
        return (
            CandidateSourceHit(
                source_kind=CandidateSourceKind.LEGAL_EVIDENCE_ROUTING,
                hole_id=hole.hole_id,
                statement=statement,
                provider_id=self.adapter_id,
                provenance=provenance,
                trust=CandidateTrust.LEGAL_DELEGATED,
                budget=budget,
                source=hole.source,
                evidence_ids=tuple(
                    str(item)
                    for item in (plan.get("evidence_ids") or ())
                    if item
                ),
                kind="legal_evidence_delegation",
                metadata={
                    "compatibility_adapter": True,
                    "owns_search": False,
                },
                proposal_only=False,
                delegated_to=self.adapter_id,
            ),
        )


@dataclass(frozen=True, slots=True)
class ReviewedTemplateSource:
    """Emits reviewed template statements matched by hole kind."""

    templates: Mapping[str, Sequence[str]] = field(default_factory=dict)
    source_kind: CandidateSourceKind = CandidateSourceKind.REVIEWED_TEMPLATE
    provider_id: str = "provider:template-library"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_kind",
            _enum(self.source_kind, CandidateSourceKind, "source_kind"),
        )
        if not isinstance(self.templates, Mapping):
            raise CandidateSynthesisError("templates must be a mapping")
        normalized: dict[str, tuple[str, ...]] = {}
        for key, values in self.templates.items():
            kind_key = _text(key, "template key", maximum=128)
            if isinstance(values, str):
                stmts = (values,)
            elif isinstance(values, Sequence):
                stmts = tuple(
                    _text(item, f"templates[{kind_key}]", maximum=8192)
                    for item in values
                )
            else:
                raise CandidateSynthesisError(
                    f"templates[{kind_key}] must be a string or sequence"
                )
            normalized[kind_key] = stmts
        object.__setattr__(self, "templates", normalized)
        object.__setattr__(
            self,
            "provider_id",
            _text(self.provider_id, "provider_id", maximum=256),
        )

    def propose(
        self,
        hole: ProofHole,
        *,
        budget: ResourceBounds,
    ) -> Sequence[CandidateSourceHit]:
        statements = self.templates.get(hole.kind.value, ())
        hits: list[CandidateSourceHit] = []
        for index, statement in enumerate(statements):
            hits.append(
                CandidateSourceHit(
                    source_kind=self.source_kind,
                    hole_id=hole.hole_id,
                    statement=statement,
                    provider_id=self.provider_id,
                    provenance={
                        "template_kind": hole.kind.value,
                        "template_index": index,
                        "reviewed": True,
                    },
                    trust=CandidateTrust.TEMPLATE,
                    budget=budget,
                    source=hole.source,
                    kind=f"template:{hole.kind.value}",
                    metadata={"template_index": index},
                )
            )
        return tuple(hits)


# ---------------------------------------------------------------------------
# Portfolio synthesizer
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofCandidatePortfolio:
    """Compose typed candidate sources into a proof-candidate portfolio.

    Interface: ``ProofCandidatePortfolio@1``

    Owns composition and ranking of candidate sources. Reuses injected
    adapters for corpus/cache/Hammer/solvers/legal/learned providers and
    never claims proof authority.
    """

    INTERFACE: ClassVar[str] = PROOF_CANDIDATE_PORTFOLIO_INTERFACE
    ALGORITHM_VERSION: ClassVar[str] = PORTFOLIO_ALGORITHM_VERSION

    sources: tuple[CandidateSourceAdapter, ...] = ()
    budget: ResourceBounds = field(default_factory=lambda: DEFAULT_BUDGET)
    include_builtin_legal_adapter: bool = True
    max_candidates_per_hole: int = 16
    formal_goal_id: str = ""

    def __post_init__(self) -> None:
        normalized: list[Any] = []
        for index, source in enumerate(self.sources):
            if not hasattr(source, "propose"):
                raise CandidateSynthesisError(
                    f"sources[{index}] must provide propose(hole, budget=...)"
                )
            if not hasattr(source, "source_kind"):
                raise CandidateSynthesisError(
                    f"sources[{index}] must expose source_kind"
                )
            normalized.append(source)
        if self.include_builtin_legal_adapter:
            has_legal = any(
                getattr(item, "source_kind", None)
                is CandidateSourceKind.LEGAL_EVIDENCE_ROUTING
                or getattr(item, "source_kind", None)
                == CandidateSourceKind.LEGAL_EVIDENCE_ROUTING
                for item in normalized
            )
            if not has_legal:
                normalized.append(LegalEvidenceRoutingAdapter())
        object.__setattr__(self, "sources", tuple(normalized))
        object.__setattr__(self, "budget", _bounds(self.budget, "budget"))
        object.__setattr__(
            self,
            "include_builtin_legal_adapter",
            _bool(
                self.include_builtin_legal_adapter,
                "include_builtin_legal_adapter",
            ),
        )
        object.__setattr__(
            self,
            "max_candidates_per_hole",
            _nonnegative_int(
                self.max_candidates_per_hole, "max_candidates_per_hole"
            ),
        )
        if self.max_candidates_per_hole == 0:
            # Fall back to budget max_candidates or a small default.
            limit = self.budget.max_candidates or 16
            object.__setattr__(self, "max_candidates_per_hole", limit)
        object.__setattr__(
            self,
            "formal_goal_id",
            _text(
                self.formal_goal_id,
                "formal_goal_id",
                optional=True,
                maximum=256,
            ),
        )

    def synthesize(
        self,
        holes: Sequence[ProofHole | Mapping[str, Any]],
        *,
        budget: ResourceBounds | Mapping[str, Any] | None = None,
        formal_goal_id: str | None = None,
        extra_hits: Sequence[CandidateSourceHit | Mapping[str, Any]] = (),
    ) -> CandidatePortfolioResult:
        """Synthesize candidates for each hole from all registered sources."""

        if holes is None:
            raise CandidateSynthesisError("holes is required")
        if not isinstance(holes, Sequence) or isinstance(
            holes, (str, bytes, bytearray, memoryview)
        ):
            raise CandidateSynthesisError("holes must be a sequence of ProofHole")

        resolved_holes: list[ProofHole] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(holes):
            hole = _proof_hole(raw, f"holes[{index}]")
            if hole.hole_id in seen_ids:
                raise CandidateSynthesisError(
                    f"duplicate hole id {hole.hole_id!r}"
                )
            seen_ids.add(hole.hole_id)
            # Non-proof diagnostics are not candidate targets.
            if hole.status in {
                HoleStatus.UNSUPPORTED,
                HoleStatus.UNAVAILABLE,
                HoleStatus.FALSE,
            }:
                continue
            if hole.kind in {
                HoleKind.UNSUPPORTED_SEMANTICS,
                HoleKind.UNAVAILABLE_TOOL,
                HoleKind.UNAVAILABLE_RECONSTRUCTION,
                HoleKind.REQUIRED_IMPLEMENTATION_CHANGE,
            }:
                continue
            resolved_holes.append(hole)

        active_budget = _bounds(
            budget if budget is not None else self.budget, "budget"
        )
        goal_id = _text(
            formal_goal_id
            if formal_goal_id is not None
            else self.formal_goal_id,
            "formal_goal_id",
            optional=True,
            maximum=256,
        )
        if not goal_id and resolved_holes:
            goal_id = resolved_holes[0].formal_goal_id

        all_hits: list[CandidateSourceHit] = []
        for hole in resolved_holes:
            for source in self.sources:
                try:
                    hits = source.propose(hole, budget=active_budget)
                except CandidateSynthesisError:
                    raise
                except Exception as error:  # pragma: no cover - adapter faults
                    raise CandidateSynthesisError(
                        f"source {getattr(source, 'source_kind', source)!r} "
                        f"failed for hole {hole.hole_id!r}: {error}"
                    ) from error
                if hits is None:
                    continue
                if not isinstance(hits, Sequence) or isinstance(
                    hits, (str, bytes)
                ):
                    raise CandidateSynthesisError(
                        f"source {source.source_kind!r} must return a sequence of hits"
                    )
                for hit_index, hit in enumerate(hits):
                    if isinstance(hit, Mapping):
                        hit = CandidateSourceHit.from_dict(
                            {
                                "source_kind": getattr(
                                    source, "source_kind", CandidateSourceKind.REVIEWED_TEMPLATE
                                ),
                                "hole_id": hole.hole_id,
                                **dict(hit),
                            }
                        )
                    elif not isinstance(hit, CandidateSourceHit):
                        raise CandidateSynthesisError(
                            f"source hit[{hit_index}] must be a CandidateSourceHit"
                        )
                    if hit.hole_id != hole.hole_id:
                        hit = replace(hit, hole_id=hole.hole_id)
                    all_hits.append(hit)

        for index, raw_hit in enumerate(extra_hits):
            if isinstance(raw_hit, Mapping):
                all_hits.append(CandidateSourceHit.from_dict(raw_hit))
            elif isinstance(raw_hit, CandidateSourceHit):
                all_hits.append(raw_hit)
            else:
                raise CandidateSynthesisError(
                    f"extra_hits[{index}] must be a CandidateSourceHit"
                )

        hole_by_id = {hole.hole_id: hole for hole in resolved_holes}
        proposals: list[CandidateProposal] = []
        per_hole_count: dict[str, int] = {hole.hole_id: 0 for hole in resolved_holes}

        # Deterministic order: rank desc, source kind, statement, provider.
        ordered_hits = sorted(
            all_hits,
            key=lambda hit: (
                -hit.rank_score_millionths,
                hit.source_kind.value,
                hit.statement,
                hit.provider_id,
                hit.hole_id,
            ),
        )

        for hit in ordered_hits:
            hole = hole_by_id.get(hit.hole_id)
            if hole is None:
                # Extra hits may target unknown holes only if hole id present.
                # Skip orphans to keep portfolio bound to supplied holes.
                continue
            count = per_hole_count.get(hit.hole_id, 0)
            limit = min(
                self.max_candidates_per_hole,
                active_budget.max_candidates or self.max_candidates_per_hole,
            )
            if limit and count >= limit:
                continue
            proposal = self._hit_to_proposal(hit=hit, hole=hole)
            proposals.append(proposal)
            per_hole_count[hit.hole_id] = count + 1

        # Global max_candidates cap (if set on budget).
        global_cap = active_budget.max_candidates
        if global_cap and len(proposals) > global_cap:
            proposals = proposals[:global_cap]

        proposals_sorted = tuple(
            sorted(
                proposals,
                key=lambda item: (
                    -item.step.rank_score_millionths,
                    item.source_kind.value,
                    item.candidate_id,
                ),
            )
        )

        source_kinds = tuple(
            sorted({item.source_kind.value for item in proposals_sorted})
        )
        proposal_only_ids = tuple(
            item.candidate_id
            for item in proposals_sorted
            if item.proposal_only
        )
        legal_ids = tuple(
            item.candidate_id
            for item in proposals_sorted
            if item.source_kind is CandidateSourceKind.LEGAL_EVIDENCE_ROUTING
            or item.delegated_to
        )
        targeted = tuple(hole.hole_id for hole in resolved_holes)
        portfolio_id = (
            "portfolio:"
            + hashlib.sha256(
                json.dumps(
                    {
                        "formal_goal_id": goal_id,
                        "hole_ids": list(targeted),
                        "candidate_ids": [
                            item.candidate_id for item in proposals_sorted
                        ],
                        "algorithm": self.ALGORITHM_VERSION,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:20]
        )
        return CandidatePortfolioResult(
            portfolio_id=portfolio_id,
            formal_goal_id=goal_id,
            proposals=proposals_sorted,
            targeted_hole_ids=targeted,
            source_kinds_used=source_kinds,
            proposal_only_candidate_ids=proposal_only_ids,
            legal_delegated_candidate_ids=legal_ids,
            algorithm_version=self.ALGORITHM_VERSION,
            budget=active_budget,
            proof_claimed=False,
            completion_claimed=False,
            metadata={
                "source_count": len(self.sources),
                "hit_count": len(all_hits),
            },
        )

    def _hit_to_proposal(
        self,
        *,
        hit: CandidateSourceHit,
        hole: ProofHole,
    ) -> CandidateProposal:
        proposal_only = bool(hit.proposal_only) or is_proposal_only_source(
            hit.source_kind
        )
        authority = _cap_authority_for_source(
            hit.source_kind, AuthorityCeiling.CANDIDATE
        )
        if proposal_only:
            authority = AuthorityCeiling.CANDIDATE

        provenance = {
            **dict(hit.provenance),
            "source_kind": hit.source_kind.value,
            "trust": hit.trust.value if hit.trust is not None else CandidateTrust.UNKNOWN.value,
            "provider_id": hit.provider_id,
            "proposal_only": proposal_only,
            "targeted_hole_ids": [hole.hole_id],
            "hole_kind": hole.kind.value,
        }
        if hit.delegated_to:
            provenance["delegated_to"] = hit.delegated_to
        if hit.budget is not None:
            provenance["budget"] = {
                "wall_time_ms": hit.budget.wall_time_ms,
                "max_candidates": hit.budget.max_candidates,
                "network_allowed": hit.budget.network_allowed,
            }

        candidate_id = _stable_candidate_id(
            hit.source_kind.value,
            hole.hole_id,
            hit.provider_id,
            hit.statement,
        )
        # Prefer readable prefix when short enough.
        readable = (
            f"candidate:{hit.source_kind.value}:{hole.hole_id}"
        )
        if len(readable) <= 256:
            # Still content-stabilize with digest suffix for uniqueness.
            candidate_id = f"{readable}:{candidate_id.rsplit(':', 1)[-1]}"

        source_binding = hit.source
        if not source_binding.source_ref_ids and not source_binding.span_ids:
            source_binding = hole.source

        try:
            step = CandidateProofStep(
                candidate_id=candidate_id,
                hole_id=hole.hole_id,
                kind=hit.kind or hit.source_kind.value,
                statement=hit.statement,
                status=CandidateStatus.PROPOSED,
                source=source_binding,
                provider_ids=(hit.provider_id,),
                authority=authority,
                rank_score_millionths=hit.rank_score_millionths,
                new_assumption_ids=hit.new_assumption_ids,
                evidence_ids=hit.evidence_ids,
                provenance=provenance,
                proof_claimed=False,
                completion_claimed=False,
            )
        except TacticianContractError as error:
            raise CandidateSynthesisError(
                f"failed to build CandidateProofStep for {hole.hole_id}: {error}"
            ) from error

        budget = hit.budget if hit.budget is not None else self.budget
        return CandidateProposal(
            candidate_id=candidate_id,
            source_kind=hit.source_kind,
            provider_id=hit.provider_id,
            provenance=provenance,
            trust=hit.trust if hit.trust is not None else CandidateTrust.UNKNOWN,
            budget=budget,
            targeted_hole_ids=(hole.hole_id,),
            step=step,
            proposal_only=proposal_only,
            delegated_to=hit.delegated_to,
            metadata=dict(hit.metadata),
        )


def synthesize_candidate_portfolio(
    holes: Sequence[ProofHole | Mapping[str, Any]],
    *,
    sources: Sequence[CandidateSourceAdapter] = (),
    budget: ResourceBounds | Mapping[str, Any] | None = None,
    formal_goal_id: str = "",
    extra_hits: Sequence[CandidateSourceHit | Mapping[str, Any]] = (),
    include_builtin_legal_adapter: bool = True,
) -> CandidatePortfolioResult:
    """Convenience entry point for ``ProofCandidatePortfolio@1``."""

    return ProofCandidatePortfolio(
        sources=tuple(sources),
        budget=_bounds(budget, "budget") if budget is not None else DEFAULT_BUDGET,
        include_builtin_legal_adapter=include_builtin_legal_adapter,
        formal_goal_id=formal_goal_id,
    ).synthesize(
        holes,
        budget=budget,
        formal_goal_id=formal_goal_id or None,
        extra_hits=extra_hits,
    )


def default_source_kinds() -> tuple[CandidateSourceKind, ...]:
    """Return the closed portfolio source vocabulary in documentation order."""

    return (
        CandidateSourceKind.CORPUS_EXACT,
        CandidateSourceKind.CACHE_HIT,
        CandidateSourceKind.HAMMER_RETRIEVAL,
        CandidateSourceKind.REVIEWED_TEMPLATE,
        CandidateSourceKind.HOUDINI_ELIMINATION,
        CandidateSourceKind.SMT_UNSAT_CORE,
        CandidateSourceKind.SMT_INTERPOLATION,
        CandidateSourceKind.CHC_PDR_IC3,
        CandidateSourceKind.SYGUS,
        CandidateSourceKind.LEGAL_EVIDENCE_ROUTING,
        CandidateSourceKind.LEARNED_AUTOENCODER,
        CandidateSourceKind.LEARNED_LEANSTRAL,
        CandidateSourceKind.LEARNED_SYMAI,
        CandidateSourceKind.LEARNED_EMBEDDINGS,
        CandidateSourceKind.LEARNED_MODEL,
    )


__all__ = [
    "PROOF_CANDIDATE_PORTFOLIO_INTERFACE",
    "CANDIDATE_SYNTHESIS_SCHEMA",
    "CANDIDATE_SOURCE_HIT_SCHEMA",
    "CANDIDATE_PROPOSAL_SCHEMA",
    "PORTFOLIO_RESULT_SCHEMA",
    "PORTFOLIO_ALGORITHM_VERSION",
    "LEGAL_TACTICIAN_ADAPTER_ID",
    "LEGAL_TACTICIAN_MODULE",
    "LEGAL_TACTICIAN_CLASS",
    "DEFAULT_BUDGET",
    "PROPOSAL_ONLY_PROVIDER_PREFIXES",
    "CANDIDATE_PROOF_STEP_SCHEMA",
    "CandidateSynthesisError",
    "CandidateSourceKind",
    "CandidateTrust",
    "CandidateSourceHit",
    "CandidateProposal",
    "CandidatePortfolioResult",
    "CandidateSourceAdapter",
    "StaticCandidateSource",
    "LegalEvidenceRoutingAdapter",
    "ReviewedTemplateSource",
    "ProofCandidatePortfolio",
    "synthesize_candidate_portfolio",
    "default_source_kinds",
    "is_proposal_only_source",
    "is_proposal_only_provider",
    "is_legal_hole",
]
