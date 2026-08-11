"""Gate ErgoAI and SymbolicAI proposals through deterministic parsing (LFP2-035).

Interface: ``AdvisorProviderEvidence@2``

ErgoAI and SymbolicAI remain proposal/advisor providers only.  This module:

* types ErgoAI / SymAI (SymbolicAI) requests and results;
* reparses **all** proposed source through deterministic frontends
  (``FLogicFrontend@2`` for ErgoAI; ``AdvisorCandidateParser@1`` plus rule /
  frame frontends for SymbolicAI);
* checks signatures and declared features against the typed elaboration; and
* emits only ``unverified_candidate_only`` material until independent
  solver/kernel validation.

Authority fail-closed (acceptance LFP2-035):

* confidence never establishes parse correctness, satisfiability, policy, or proof;
* fluent natural-language text never establishes those claims;
* provider availability never establishes those claims;
* mock output never establishes those claims.

Successful deterministic parse/elaboration may mark parse correctness only.
It never yields satisfiability, policy, or proof authority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
    role_can_satisfy_certified_authority,
)
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    evidence_id,
    lane_id,
    provider_id,
)
from ipfs_datasets_py.logic.formalization.advisor_parser_adapter import (
    ADVISOR_CANDIDATE_PARSER_INTERFACE,
    AdvisorCandidateParser,
    AdvisorNotation,
    AdvisorParseResult,
    normalize_notation,
)
from ipfs_datasets_py.logic.formalization.proposal_advisors import (
    UNVERIFIED_AUTHORITY,
    ProposalAcceptance,
    ProposalCandidate,
    ProposalKind,
    ProposalProvider,
    accept_candidate,
    confidence_never_yields_proof,
)
from ipfs_datasets_py.logic.parsers.flogic_v2 import (
    ERGOAI_CONTROLLED_SOURCE_V2_INTERFACE,
    FLOGIC_FRONTEND_V2_INTERFACE,
    FLOGIC_V2_FAMILY_ID,
    FLOGIC_V2_PROFILE_ID,
    ErgoAIControlledSourceV2,
    FLogicFrontendV2,
    FLogicFrontendV2Result,
)
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SyntaxContractError,
    _freeze_mapping,
    _record_id,
    _require_mapping,
    _require_sequence,
    _sha256_hex,
    _text,
    _thaw_mapping,
    canonical_json_bytes,
    content_sha256,
)
from ipfs_datasets_py.logic.syntax_core.signatures import LogicSignature

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

ADVISOR_PROVIDER_EVIDENCE_V2_INTERFACE: Final = "AdvisorProviderEvidence@2"
ADVISOR_EXECUTION_REQUEST_V2_INTERFACE: Final = "AdvisorExecutionRequest@2"
ADVISOR_EXECUTION_RESULT_V2_INTERFACE: Final = "AdvisorExecutionResult@2"

ADVISOR_PROVIDER_EVIDENCE_SCHEMA: Final = "advisor-provider-evidence/v2"
ADVISOR_EXECUTION_REQUEST_SCHEMA: Final = "advisor-execution-request/v2"
ADVISOR_EXECUTION_RESULT_SCHEMA: Final = "advisor-execution-result/v2"
ADVISOR_REPARSE_RECORD_SCHEMA: Final = "advisor-reparse-record/v2"
ADVISOR_EXECUTION_V2_MODULE_VERSION: Final = "1.0.0"
ADVISOR_EXECUTION_V2_TASK_ID: Final = "LFP2-035"
ADVISOR_EXECUTION_V2_GOAL_ID: Final = "LFP2-G060"

ADVISOR_LANE_ID: Final = "advisor"
ADVISOR_EVIDENCE_KIND: Final = "candidate"

_FEATURE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}$")
_MAX_SOURCE_CHARS: Final = 16_384
_MAX_FLUENT_CHARS: Final = 8_192
_MAX_SOURCE_REFS: Final = 64
_MAX_FEATURES: Final = 128
_MAX_DIAGNOSTICS: Final = 256
_MAX_METADATA_BYTES: Final = 8_192

# Signals that must never establish authority claims.
_NON_DETERMINISTIC_SIGNAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "availability",
        "available",
        "confidence",
        "fluent_text",
        "is_valid",
        "mock",
        "mock_output",
        "similarity",
    }
)

_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "arbitrary_payload",
        "authorization_status",
        "claimed_execution",
        "claimed_proof",
        "execution_result",
        "fake_replay",
        "family_string",
        "free_form_family",
        "is_proved",
        "logic_family",
        "mock_execution",
        "mock_result",
        "opaque_extension",
        "payload",
        "proof_result",
        "proof_status",
        "proved",
        "raw_formula",
        "raw_result",
        "raw_source",
        "solver_result",
        "target_source",
        "verification_result",
        "verification_status",
    }
)


class AdvisorExecutionError(SyntaxContractError):
    """Raised when advisor execution v2 inputs or evidence are malformed."""


class AdvisorAuthorityError(AdvisorExecutionError):
    """Raised when a claim would exceed the advisor authority ceiling."""


class AdvisorProviderKind(StrEnum):
    """Closed set of advisor providers gated by this module."""

    ERGOAI = "ergoai"
    SYMBOLICAI = "symbolicai"
    SYMAI = "symai"


class AdvisorClaimKind(StrEnum):
    """Claims that non-deterministic signals must never establish."""

    PARSE_CORRECTNESS = "parse_correctness"
    SATISFIABILITY = "satisfiability"
    POLICY = "policy"
    PROOF = "proof"


class AdvisorGateDisposition(StrEnum):
    """Closed set of deterministic gate outcomes."""

    TYPED_CANDIDATE = "typed_candidate"
    PARSE_FAILED = "parse_failed"
    FEATURE_MISMATCH = "feature_mismatch"
    SIGNATURE_FAILED = "signature_failed"
    MOCK_REJECTED = "mock_rejected"
    EMPTY_SOURCE = "empty_source"
    UNSUPPORTED_PROVIDER = "unsupported_provider"
    AUTHORITY_REJECTED = "authority_rejected"


_PROVIDER_ALIASES: Final[dict[str, AdvisorProviderKind]] = {
    "ergoai": AdvisorProviderKind.ERGOAI,
    "ergo": AdvisorProviderKind.ERGOAI,
    "ergo_engine": AdvisorProviderKind.ERGOAI,
    "symbolicai": AdvisorProviderKind.SYMBOLICAI,
    "symbolic_ai": AdvisorProviderKind.SYMBOLICAI,
    "symai": AdvisorProviderKind.SYMAI,
    "sym_ai": AdvisorProviderKind.SYMAI,
}


def normalize_advisor_provider(
    value: AdvisorProviderKind | ProposalProvider | str,
) -> AdvisorProviderKind:
    """Normalize provider labels into the closed advisor provider set."""

    if isinstance(value, AdvisorProviderKind):
        return value
    if isinstance(value, ProposalProvider):
        if value is ProposalProvider.SYMAI:
            return AdvisorProviderKind.SYMAI
        raise AdvisorExecutionError(
            f"proposal provider {value.value!r} is not an ErgoAI/SymbolicAI advisor"
        )
    key = str(value).strip().lower().replace("-", "_")
    if key not in _PROVIDER_ALIASES:
        raise AdvisorExecutionError(
            f"unsupported advisor provider: {value!r}; "
            f"expected one of {sorted(set(_PROVIDER_ALIASES.values()), key=lambda p: p.value)}"
        )
    return _PROVIDER_ALIASES[key]


def is_symbolicai_provider(provider: AdvisorProviderKind) -> bool:
    return provider in {
        AdvisorProviderKind.SYMBOLICAI,
        AdvisorProviderKind.SYMAI,
    }


def is_ergoai_provider(provider: AdvisorProviderKind) -> bool:
    return provider is AdvisorProviderKind.ERGOAI


def provider_logic_identity(provider: AdvisorProviderKind) -> LogicIdentity:
    """Return the canonical provider identity for matrix / evidence binding."""

    if is_symbolicai_provider(provider):
        # SymbolicAI and symai share the symbolicai provider id in the matrix.
        return provider_id("symbolicai")
    return provider_id("ergoai")


def non_deterministic_signal_establishes(
    claim: AdvisorClaimKind | str,
    *,
    confidence: float | None = None,
    fluent_text: str | None = None,
    available: bool | None = None,
    mock_output: object = None,
    is_valid: bool | None = None,
    similarity: float | None = None,
) -> bool:
    """Always ``False``: confidence / fluent text / availability / mock cannot establish claims.

    Arguments are accepted so call sites can pass through untrusted proposal
    fields without elevating them.  Covers parse correctness, satisfiability,
    policy, and proof (LFP2-035 acceptance).
    """

    del (
        claim,
        confidence,
        fluent_text,
        available,
        mock_output,
        is_valid,
        similarity,
    )
    return False


def advisor_never_establishes_proof(
    *,
    confidence: float | None = None,
    fluent_text: str | None = None,
    available: bool | None = None,
    mock_output: object = None,
    parse_ok: bool = False,
    independently_validated: bool = False,
) -> bool:
    """Advisors never mint proof authority, even after a successful reparse."""

    del confidence, fluent_text, available, mock_output, parse_ok, independently_validated
    return confidence_never_yields_proof()


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip())
    except (TypeError, ValueError) as error:
        allowed = ", ".join(item.value for item in enum_type)
        raise AdvisorExecutionError(
            f"{field_name} must be one of: {allowed}; got {value!r}"
        ) from error


def _unit_interval(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdvisorExecutionError(f"{field_name} must be numeric")
    result = float(value)
    if result != result or result < 0.0 or result > 1.0:  # NaN guard
        raise AdvisorExecutionError(f"{field_name} must be a finite value in [0, 1]")
    return result


def _feature_tuple(value: object, field_name: str = "features") -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if len(items) > _MAX_FEATURES:
        raise AdvisorExecutionError(f"{field_name} exceeds hard limit {_MAX_FEATURES}")
    out: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        feature = _text(item, f"{field_name}[{index}]", maximum=256)
        if not _FEATURE_RE.fullmatch(feature):
            raise AdvisorExecutionError(
                f"{field_name}[{index}] must be a stable feature path; got {feature!r}"
            )
        if feature not in seen:
            seen.add(feature)
            out.append(feature)
    return tuple(out)


def _source_ref_ids(value: object, field_name: str = "source_ref_ids") -> tuple[str, ...]:
    items = _require_sequence(value, field_name)
    if not items:
        raise AdvisorExecutionError(
            f"{field_name} must be non-empty (proposals must be source-bound)"
        )
    if len(items) > _MAX_SOURCE_REFS:
        raise AdvisorExecutionError(
            f"{field_name} exceeds hard limit {_MAX_SOURCE_REFS}"
        )
    refs: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        ref = _record_id(item, f"{field_name}[{index}]")
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return tuple(refs)


def _forbid_authority_metadata(metadata: Mapping[str, Any], field_name: str) -> None:
    for key in metadata:
        if key in _FORBIDDEN_METADATA_KEYS or key in _NON_DETERMINISTIC_SIGNAL_KEYS:
            raise AdvisorAuthorityError(
                f"{field_name} rejects free-form authority/signal key {key!r}; "
                "use typed advisor evidence fields only"
            )


def _optional_bool(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise AdvisorExecutionError(f"{field_name} must be a boolean")


def _digest_of(payload: Mapping[str, Any]) -> str:
    return content_sha256(canonical_json_bytes(dict(payload)))


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdvisorExecutionRequestV2:
    """Typed ErgoAI / SymbolicAI proposal request for the deterministic gate.

    Interface: ``AdvisorExecutionRequest@2``.

    Non-deterministic signals (confidence, fluent text, availability, mock
    output) may be recorded for audit but never admit parse correctness,
    satisfiability, policy, or proof.
    """

    request_id: str
    provider: AdvisorProviderKind | str
    proposed_source: str
    source_ref_ids: tuple[str, ...] | Sequence[str]
    notation: AdvisorNotation | str = AdvisorNotation.AUTO
    features: tuple[str, ...] | Sequence[str] = ()
    candidate_id: str = ""
    proposal_kind: ProposalKind | str = ProposalKind.SPECIFICATION
    confidence: float = 0.0
    fluent_text: str = ""
    available: bool = False
    mock_output: Mapping[str, Any] | None = None
    independently_validated: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ADVISOR_EXECUTION_REQUEST_SCHEMA

    interface: ClassVar[str] = ADVISOR_EXECUTION_REQUEST_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self, "provider", normalize_advisor_provider(self.provider)
        )
        # Strip like proposal_advisors.sanitize_inert_text: trailing newlines
        # from multi-line formulas are not identity-significant for gating.
        if not isinstance(self.proposed_source, str):
            raise AdvisorExecutionError("proposed_source must be a string")
        if "\x00" in self.proposed_source:
            raise AdvisorExecutionError(
                "proposed_source must not contain NUL bytes"
            )
        source = self.proposed_source.replace("\r\n", "\n").replace("\r", "\n")
        source = source.strip()
        if len(source) > _MAX_SOURCE_CHARS:
            raise AdvisorExecutionError(
                f"proposed_source exceeds hard limit {_MAX_SOURCE_CHARS}"
            )
        object.__setattr__(self, "proposed_source", source)
        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )
        try:
            notation = normalize_notation(self.notation)  # type: ignore[arg-type]
        except Exception as error:
            raise AdvisorExecutionError(str(error)) from error
        # ErgoAI proposals always reparse as F-logic / frame source.
        if is_ergoai_provider(self.provider) and notation is AdvisorNotation.AUTO:
            notation = AdvisorNotation.FLOGIC
        object.__setattr__(self, "notation", notation)
        object.__setattr__(self, "features", _feature_tuple(self.features))
        if self.candidate_id:
            object.__setattr__(
                self, "candidate_id", _record_id(self.candidate_id, "candidate_id")
            )
        else:
            object.__setattr__(
                self,
                "candidate_id",
                f"cand:{self.provider.value}:{self.request_id}",
            )
        kind = (
            self.proposal_kind
            if isinstance(self.proposal_kind, ProposalKind)
            else ProposalKind(str(self.proposal_kind))
        )
        object.__setattr__(self, "proposal_kind", kind)
        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
        if self.fluent_text:
            if not isinstance(self.fluent_text, str):
                raise AdvisorExecutionError("fluent_text must be a string")
            fluent = self.fluent_text.replace("\r\n", "\n").replace("\r", "\n")
            fluent = fluent.strip()
            if "\x00" in fluent:
                raise AdvisorExecutionError(
                    "fluent_text must not contain NUL bytes"
                )
            if len(fluent) > _MAX_FLUENT_CHARS:
                raise AdvisorExecutionError(
                    f"fluent_text exceeds hard limit {_MAX_FLUENT_CHARS}"
                )
            object.__setattr__(self, "fluent_text", fluent)
        else:
            object.__setattr__(self, "fluent_text", "")
        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        if self.mock_output is None:
            object.__setattr__(self, "mock_output", None)
        else:
            mock = _require_mapping(self.mock_output, "mock_output")
            object.__setattr__(
                self, "mock_output", dict(_freeze_mapping(mock, "mock_output"))
            )
        object.__setattr__(
            self,
            "independently_validated",
            _optional_bool(self.independently_validated, "independently_validated"),
        )
        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        if len(canonical_json_bytes(dict(metadata))) > _MAX_METADATA_BYTES:
            raise AdvisorExecutionError("metadata exceeds byte bound")
        object.__setattr__(self, "metadata", metadata)
        if self.schema_version != ADVISOR_EXECUTION_REQUEST_SCHEMA:
            raise AdvisorExecutionError(
                f"unsupported AdvisorExecutionRequest@2 schema: "
                f"{self.schema_version!r}"
            )

    @property
    def provider_identity(self) -> LogicIdentity:
        return provider_logic_identity(self.provider)  # type: ignore[arg-type]

    @property
    def lane(self) -> LogicIdentity:
        return lane_id(ADVISOR_LANE_ID)

    @property
    def evidence_kind(self) -> LogicIdentity:
        return evidence_id(ADVISOR_EVIDENCE_KIND)

    @property
    def source_digest(self) -> str:
        return content_sha256(self.proposed_source.encode("utf-8"))

    @property
    def has_mock_output(self) -> bool:
        return self.mock_output is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "candidate_id": self.candidate_id,
            "confidence": self.confidence,
            "evidence_kind": self.evidence_kind.to_dict(),
            "features": list(self.features),
            "fluent_text": self.fluent_text,
            "has_mock_output": self.has_mock_output,
            "independently_validated": self.independently_validated,
            "interface": self.interface,
            "lane": self.lane.to_dict(),
            "metadata": _thaw_mapping(self.metadata),
            "mock_output": None if self.mock_output is None else dict(self.mock_output),
            "notation": (
                self.notation.value
                if isinstance(self.notation, AdvisorNotation)
                else self.notation
            ),
            "proposal_kind": (
                self.proposal_kind.value
                if isinstance(self.proposal_kind, ProposalKind)
                else self.proposal_kind
            ),
            "proposed_source": self.proposed_source,
            "provider": (
                self.provider.value
                if isinstance(self.provider, AdvisorProviderKind)
                else self.provider
            ),
            "provider_identity": self.provider_identity.to_dict(),
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_ref_ids": list(self.source_ref_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AdvisorExecutionRequestV2":
        payload = _require_mapping(value, "AdvisorExecutionRequest@2")
        return cls(
            request_id=payload.get("request_id", ""),
            provider=payload.get("provider", ""),
            proposed_source=payload.get("proposed_source", ""),
            source_ref_ids=tuple(payload.get("source_ref_ids", ())),
            notation=payload.get("notation", AdvisorNotation.AUTO),
            features=tuple(payload.get("features", ())),
            candidate_id=str(payload.get("candidate_id", "") or ""),
            proposal_kind=payload.get(
                "proposal_kind", ProposalKind.SPECIFICATION
            ),
            confidence=payload.get("confidence", 0.0),
            fluent_text=str(payload.get("fluent_text", "") or ""),
            available=bool(payload.get("available", False)),
            mock_output=payload.get("mock_output"),
            independently_validated=bool(
                payload.get("independently_validated", False)
            ),
            metadata=dict(payload.get("metadata") or {}),
            schema_version=payload.get(
                "schema_version", ADVISOR_EXECUTION_REQUEST_SCHEMA
            ),
        )

    @classmethod
    def from_proposal_candidate(
        cls,
        candidate: ProposalCandidate,
        *,
        request_id: str,
        provider: AdvisorProviderKind | str | None = None,
        notation: AdvisorNotation | str = AdvisorNotation.AUTO,
        features: Sequence[str] = (),
        fluent_text: str = "",
        available: bool = False,
        mock_output: Mapping[str, Any] | None = None,
        independently_validated: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> "AdvisorExecutionRequestV2":
        """Lift a :class:`ProposalCandidate` into a typed advisor execution request."""

        if not isinstance(candidate, ProposalCandidate):
            raise AdvisorExecutionError("candidate must be a ProposalCandidate")
        if candidate.authority != UNVERIFIED_AUTHORITY:
            raise AdvisorAuthorityError(
                "only unverified proposal candidates may enter the advisor gate"
            )
        resolved_provider: AdvisorProviderKind | str
        if provider is not None:
            resolved_provider = provider
        elif candidate.provider is ProposalProvider.SYMAI:
            resolved_provider = AdvisorProviderKind.SYMAI
        else:
            raise AdvisorExecutionError(
                "from_proposal_candidate requires an explicit ErgoAI/SymbolicAI "
                f"provider when candidate.provider is {candidate.provider!r}"
            )
        return cls(
            request_id=request_id,
            provider=resolved_provider,
            proposed_source=candidate.body,
            source_ref_ids=candidate.source_ref_ids,
            notation=notation,
            features=tuple(features),
            candidate_id=candidate.candidate_id,
            proposal_kind=candidate.kind,
            confidence=candidate.confidence,
            fluent_text=fluent_text or candidate.rationale,
            available=available,
            mock_output=mock_output,
            independently_validated=independently_validated,
            metadata=dict(metadata or {}),
        )


# ---------------------------------------------------------------------------
# Reparse record / evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdvisorReparseRecord:
    """Deterministic record of one proposed-source reparse attempt."""

    disposition: AdvisorGateDisposition | str
    parse_ok: bool = False
    type_ok: bool = False
    signature_ok: bool = False
    features_ok: bool = False
    parser_interface: str = ""
    logic_family: str = ""
    logic_profile: str = ""
    discovered_features: tuple[str, ...] = ()
    missing_features: tuple[str, ...] = ()
    signature_id: str = ""
    expression_id: str = ""
    expression_digest: str = ""
    diagnostics: tuple[str, ...] = ()
    typed_kind: str = ""
    schema_version: str = ADVISOR_REPARSE_RECORD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, AdvisorGateDisposition, "disposition"),
        )
        for flag in ("parse_ok", "type_ok", "signature_ok", "features_ok"):
            if not isinstance(getattr(self, flag), bool):
                raise AdvisorExecutionError(f"{flag} must be a boolean")
        object.__setattr__(
            self, "parser_interface", str(self.parser_interface or "")
        )
        object.__setattr__(self, "logic_family", str(self.logic_family or ""))
        object.__setattr__(self, "logic_profile", str(self.logic_profile or ""))
        object.__setattr__(
            self,
            "discovered_features",
            _feature_tuple(self.discovered_features, "discovered_features"),
        )
        object.__setattr__(
            self,
            "missing_features",
            _feature_tuple(self.missing_features, "missing_features"),
        )
        object.__setattr__(self, "signature_id", str(self.signature_id or ""))
        object.__setattr__(self, "expression_id", str(self.expression_id or ""))
        if self.expression_digest:
            object.__setattr__(
                self,
                "expression_digest",
                _sha256_hex(self.expression_digest, "expression_digest"),
            )
        diags = tuple(str(item) for item in self.diagnostics)[:_MAX_DIAGNOSTICS]
        object.__setattr__(self, "diagnostics", diags)
        object.__setattr__(self, "typed_kind", str(self.typed_kind or ""))
        if self.schema_version != ADVISOR_REPARSE_RECORD_SCHEMA:
            raise AdvisorExecutionError(
                f"unsupported reparse record schema: {self.schema_version!r}"
            )

    @property
    def reparse_succeeded(self) -> bool:
        return (
            self.parse_ok
            and self.type_ok
            and self.signature_ok
            and self.features_ok
            and self.disposition is AdvisorGateDisposition.TYPED_CANDIDATE
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": list(self.diagnostics),
            "discovered_features": list(self.discovered_features),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, AdvisorGateDisposition)
                else self.disposition
            ),
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "features_ok": self.features_ok,
            "logic_family": self.logic_family,
            "logic_profile": self.logic_profile,
            "missing_features": list(self.missing_features),
            "parse_ok": self.parse_ok,
            "parser_interface": self.parser_interface,
            "reparse_succeeded": self.reparse_succeeded,
            "schema_version": self.schema_version,
            "signature_id": self.signature_id,
            "signature_ok": self.signature_ok,
            "type_ok": self.type_ok,
            "typed_kind": self.typed_kind,
        }


@dataclass(frozen=True, slots=True)
class AdvisorProviderEvidenceV2:
    """Pinned advisor provider evidence after deterministic reparse.

    Interface: ``AdvisorProviderEvidence@2``.

    Always carries ``authority="unverified_candidate_only"`` and
    ``result_authority=candidate``.  Satisfiability, policy, and proof are
    never established.  Parse correctness is established only when the
    deterministic reparse record reports success — never from confidence,
    fluent text, availability, or mock output.
    """

    evidence_id: str
    request_id: str
    request_digest: str
    provider: AdvisorProviderKind | str
    reparse: AdvisorReparseRecord | Mapping[str, Any]
    candidate_id: str
    source_ref_ids: tuple[str, ...] | Sequence[str]
    source_digest: str
    authority: str = UNVERIFIED_AUTHORITY
    result_authority: ResultAuthority | str = ResultAuthority.CANDIDATE
    result_status: ResultStatus | str = ResultStatus.CANDIDATE
    role: ToolRole | str = ToolRole.ADVISOR
    authority_ceiling: ToolchainAuthorityCeiling | str = (
        ToolchainAuthorityCeiling.ADVISORY
    )
    confidence: float = 0.0
    fluent_text_present: bool = False
    available: bool = False
    mock_output_present: bool = False
    independently_validated: bool = False
    acceptance: ProposalAcceptance | Mapping[str, Any] | None = None
    content_digest: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ADVISOR_PROVIDER_EVIDENCE_SCHEMA

    interface: ClassVar[str] = ADVISOR_PROVIDER_EVIDENCE_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _record_id(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "request_id", _record_id(self.request_id, "request_id")
        )
        object.__setattr__(
            self,
            "request_digest",
            _sha256_hex(self.request_digest, "request_digest"),
        )
        object.__setattr__(
            self, "provider", normalize_advisor_provider(self.provider)
        )
        if isinstance(self.reparse, AdvisorReparseRecord):
            reparse = self.reparse
        else:
            reparse = AdvisorReparseRecord(
                **{
                    key: value
                    for key, value in dict(
                        _require_mapping(self.reparse, "reparse")
                    ).items()
                    if key
                    in {
                        "disposition",
                        "parse_ok",
                        "type_ok",
                        "signature_ok",
                        "features_ok",
                        "parser_interface",
                        "logic_family",
                        "logic_profile",
                        "discovered_features",
                        "missing_features",
                        "signature_id",
                        "expression_id",
                        "expression_digest",
                        "diagnostics",
                        "typed_kind",
                        "schema_version",
                    }
                }
            )
        object.__setattr__(self, "reparse", reparse)
        object.__setattr__(
            self, "candidate_id", _record_id(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "source_ref_ids", _source_ref_ids(self.source_ref_ids)
        )
        object.__setattr__(
            self, "source_digest", _sha256_hex(self.source_digest, "source_digest")
        )

        if self.authority != UNVERIFIED_AUTHORITY:
            raise AdvisorAuthorityError(
                "AdvisorProviderEvidence@2 authority must remain "
                f"{UNVERIFIED_AUTHORITY!r}"
            )
        object.__setattr__(self, "authority", UNVERIFIED_AUTHORITY)

        result_authority = (
            self.result_authority
            if isinstance(self.result_authority, ResultAuthority)
            else ResultAuthority(str(self.result_authority))
        )
        if result_authority is not ResultAuthority.CANDIDATE:
            raise AdvisorAuthorityError(
                "AdvisorProviderEvidence@2 cannot exceed candidate result authority"
            )
        object.__setattr__(self, "result_authority", ResultAuthority.CANDIDATE)

        result_status = (
            self.result_status
            if isinstance(self.result_status, ResultStatus)
            else ResultStatus(str(self.result_status))
        )
        if result_status is not ResultStatus.CANDIDATE:
            raise AdvisorAuthorityError(
                "AdvisorProviderEvidence@2 status must remain candidate"
            )
        object.__setattr__(self, "result_status", ResultStatus.CANDIDATE)

        role = self.role if isinstance(self.role, ToolRole) else ToolRole(str(self.role))
        if role is not ToolRole.ADVISOR:
            raise AdvisorAuthorityError(
                f"AdvisorProviderEvidence@2 role must be advisor; got {role!r}"
            )
        object.__setattr__(self, "role", ToolRole.ADVISOR)

        ceiling = (
            self.authority_ceiling
            if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
            else ToolchainAuthorityCeiling(str(self.authority_ceiling))
        )
        if ceiling not in {
            ToolchainAuthorityCeiling.ADVISORY,
            ToolchainAuthorityCeiling.CANDIDATE,
        }:
            raise AdvisorAuthorityError(
                "AdvisorProviderEvidence@2 ceiling must be advisory or candidate"
            )
        if role_can_satisfy_certified_authority(role, ceiling):
            raise AdvisorAuthorityError(
                "AdvisorProviderEvidence@2 cannot satisfy certified authority"
            )
        object.__setattr__(self, "authority_ceiling", ceiling)

        object.__setattr__(
            self, "confidence", _unit_interval(self.confidence, "confidence")
        )
        object.__setattr__(
            self,
            "fluent_text_present",
            _optional_bool(self.fluent_text_present, "fluent_text_present"),
        )
        object.__setattr__(
            self, "available", _optional_bool(self.available, "available")
        )
        object.__setattr__(
            self,
            "mock_output_present",
            _optional_bool(self.mock_output_present, "mock_output_present"),
        )
        object.__setattr__(
            self,
            "independently_validated",
            _optional_bool(self.independently_validated, "independently_validated"),
        )

        if self.acceptance is None:
            object.__setattr__(self, "acceptance", None)
        elif isinstance(self.acceptance, ProposalAcceptance):
            if self.acceptance.authority not in {
                UNVERIFIED_AUTHORITY,
                "candidate_admitted_for_validation",
            }:
                raise AdvisorAuthorityError(
                    "acceptance cannot claim proof authority; "
                    f"got {self.acceptance.authority!r}"
                )
            object.__setattr__(self, "acceptance", self.acceptance)
        else:
            object.__setattr__(
                self,
                "acceptance",
                ProposalAcceptance.from_dict(
                    _require_mapping(self.acceptance, "acceptance")
                ),
            )

        metadata = _freeze_mapping(self.metadata, "metadata")
        _forbid_authority_metadata(metadata, "metadata")
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != ADVISOR_PROVIDER_EVIDENCE_SCHEMA:
            raise AdvisorExecutionError(
                f"unsupported AdvisorProviderEvidence@2 schema: "
                f"{self.schema_version!r}"
            )

        if not self.content_digest:
            object.__setattr__(
                self,
                "content_digest",
                _digest_of(
                    {
                        "candidate_id": self.candidate_id,
                        "provider": self.provider.value,  # type: ignore[union-attr]
                        "reparse": self.reparse.to_dict(),
                        "request_digest": self.request_digest,
                        "request_id": self.request_id,
                        "source_digest": self.source_digest,
                    }
                ),
            )
        else:
            object.__setattr__(
                self,
                "content_digest",
                _sha256_hex(self.content_digest, "content_digest"),
            )

    # --- authority queries (fail closed) -----------------------------------

    @property
    def remains_unverified_candidate(self) -> bool:
        return self.authority == UNVERIFIED_AUTHORITY

    @property
    def is_proved(self) -> bool:
        return False

    @property
    def parse_correctness_established(self) -> bool:
        """True only when the deterministic reparse succeeded."""

        return self.reparse.reparse_succeeded  # type: ignore[union-attr]

    @property
    def satisfiability_established(self) -> bool:
        return False

    @property
    def policy_established(self) -> bool:
        return False

    @property
    def proof_established(self) -> bool:
        return False

    def claim_established(self, claim: AdvisorClaimKind | str) -> bool:
        kind = (
            claim
            if isinstance(claim, AdvisorClaimKind)
            else AdvisorClaimKind(str(claim))
        )
        if kind is AdvisorClaimKind.PARSE_CORRECTNESS:
            return self.parse_correctness_established
        return False

    def non_deterministic_claim(
        self, claim: AdvisorClaimKind | str
    ) -> bool:
        """Whether confidence / fluent text / availability / mock establish *claim*.

        Always ``False`` by construction.
        """

        return non_deterministic_signal_establishes(
            claim,
            confidence=self.confidence,
            fluent_text="present" if self.fluent_text_present else None,
            available=self.available,
            mock_output={} if self.mock_output_present else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance": (
                None
                if self.acceptance is None
                else self.acceptance.to_dict()  # type: ignore[union-attr]
            ),
            "authority": self.authority,
            "authority_ceiling": (
                self.authority_ceiling.value
                if isinstance(self.authority_ceiling, ToolchainAuthorityCeiling)
                else self.authority_ceiling
            ),
            "available": self.available,
            "candidate_id": self.candidate_id,
            "claim_parse_correctness": self.parse_correctness_established,
            "claim_policy": False,
            "claim_proof": False,
            "claim_satisfiability": False,
            "confidence": self.confidence,
            "content_digest": self.content_digest,
            "evidence_id": self.evidence_id,
            "fluent_text_present": self.fluent_text_present,
            "independently_validated": self.independently_validated,
            "interface": self.interface,
            "is_proved": False,
            "metadata": _thaw_mapping(self.metadata),
            "mock_output_present": self.mock_output_present,
            "policy_established": False,
            "proof_established": False,
            "provider": (
                self.provider.value
                if isinstance(self.provider, AdvisorProviderKind)
                else self.provider
            ),
            "provider_identity": provider_logic_identity(
                self.provider  # type: ignore[arg-type]
            ).to_dict(),
            "remains_unverified_candidate": True,
            "reparse": self.reparse.to_dict(),  # type: ignore[union-attr]
            "request_digest": self.request_digest,
            "request_id": self.request_id,
            "result_authority": ResultAuthority.CANDIDATE.value,
            "result_status": ResultStatus.CANDIDATE.value,
            "role": ToolRole.ADVISOR.value,
            "satisfiability_established": False,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_ref_ids": list(self.source_ref_ids),
        }


@dataclass(frozen=True, slots=True)
class AdvisorExecutionResultV2:
    """Typed result of one advisor execution gate invocation.

    Interface: ``AdvisorExecutionResult@2``.
    """

    request: AdvisorExecutionRequestV2
    evidence: AdvisorProviderEvidenceV2
    typed_expression: TypedExpression | None = None
    typed_document: Any | None = None
    controlled_source: ErgoAIControlledSourceV2 | None = None
    signature: LogicSignature | None = None
    schema_version: str = ADVISOR_EXECUTION_RESULT_SCHEMA

    interface: ClassVar[str] = ADVISOR_EXECUTION_RESULT_V2_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.request, AdvisorExecutionRequestV2):
            raise AdvisorExecutionError(
                "request must be an AdvisorExecutionRequestV2"
            )
        if not isinstance(self.evidence, AdvisorProviderEvidenceV2):
            raise AdvisorExecutionError(
                "evidence must be an AdvisorProviderEvidenceV2"
            )
        if self.evidence.authority != UNVERIFIED_AUTHORITY:
            raise AdvisorAuthorityError(
                "result evidence must remain unverified_candidate_only"
            )
        if self.schema_version != ADVISOR_EXECUTION_RESULT_SCHEMA:
            raise AdvisorExecutionError(
                f"unsupported AdvisorExecutionResult@2 schema: "
                f"{self.schema_version!r}"
            )

    @property
    def disposition(self) -> AdvisorGateDisposition:
        return self.evidence.reparse.disposition  # type: ignore[return-value]

    @property
    def parse_ok(self) -> bool:
        return self.evidence.reparse.parse_ok  # type: ignore[union-attr]

    @property
    def remains_unverified_candidate(self) -> bool:
        return True

    @property
    def is_proved(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        typed_payload: Any = None
        if self.typed_document is not None and hasattr(
            self.typed_document, "to_dict"
        ):
            typed_payload = self.typed_document.to_dict()
        return {
            "controlled_source": (
                None
                if self.controlled_source is None
                else self.controlled_source.to_dict()
            ),
            "disposition": self.disposition.value,
            "evidence": self.evidence.to_dict(),
            "interface": self.interface,
            "is_proved": False,
            "parse_ok": self.parse_ok,
            "remains_unverified_candidate": True,
            "request": self.request.to_dict(),
            "schema_version": self.schema_version,
            "signature": (
                None if self.signature is None else self.signature.to_dict()
            ),
            "typed_document": typed_payload,
            "typed_expression": (
                None
                if self.typed_expression is None
                else self.typed_expression.to_dict()
            ),
        }


# ---------------------------------------------------------------------------
# Feature / signature extraction
# ---------------------------------------------------------------------------


def _features_from_typed_expression(
    expression: TypedExpression | None,
) -> tuple[str, ...]:
    if expression is None:
        return ()
    discovered: set[str] = set()
    if expression.signature is not None:
        for feature in expression.signature.features:
            discovered.add(str(feature))
    root = expression.root
    if hasattr(root, "features"):
        for feature in getattr(root, "features") or ():
            discovered.add(str(feature))
    # Always include parse/elaborate markers when a typed expression exists.
    discovered.update({"parse", "elaborate"})
    return tuple(sorted(f for f in discovered if _FEATURE_RE.fullmatch(f)))


def _features_from_document(document: Any, notation: AdvisorNotation) -> tuple[str, ...]:
    discovered: set[str] = {"parse"}
    if notation is AdvisorNotation.FLOGIC:
        discovered.update({"flogic", "frame", "elaborate"})
        if hasattr(document, "frame_object_ids") and document.frame_object_ids:
            discovered.add("frame_slots")
        if hasattr(document, "class_names") and document.class_names:
            discovered.add("inheritance")
        if hasattr(document, "statements"):
            for stmt in document.statements:
                kind = getattr(stmt, "kind", None)
                kind_value = kind.value if hasattr(kind, "value") else str(kind or "")
                if kind_value == "query":
                    discovered.add("query")
                if kind_value == "rule":
                    discovered.add("rule")
    elif notation is AdvisorNotation.SMTLIB2:
        discovered.update({"smtlib2", "first_order"})
        if hasattr(document, "feature_tags"):
            for tag in document.feature_tags() or ():
                value = tag.value if hasattr(tag, "value") else str(tag)
                # Normalize SMT feature tags into feature paths.
                token = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
                if token and _FEATURE_RE.fullmatch(token):
                    discovered.add(token)
    elif notation is AdvisorNotation.TPTP:
        discovered.update({"tptp", "first_order"})
    elif notation is AdvisorNotation.RULES:
        discovered.update({"rules", "datalog"})
    elif notation is AdvisorNotation.SECPAL:
        discovered.update({"rules", "secpal", "authorization"})
    return tuple(sorted(f for f in discovered if _FEATURE_RE.fullmatch(f)))


def _check_declared_features(
    declared: Sequence[str],
    discovered: Sequence[str],
) -> tuple[bool, tuple[str, ...]]:
    """Return (ok, missing).  Empty declared means no feature constraint."""

    if not declared:
        return True, ()
    discovered_set = set(discovered)
    missing = tuple(sorted(feature for feature in declared if feature not in discovered_set))
    return (not missing), missing


def _signature_ok(
    signature: LogicSignature | None,
    *,
    parse_ok: bool,
    typed_document: Any | None,
) -> tuple[bool, str]:
    if signature is not None:
        # A constructed LogicSignature already enforced invariants.
        return True, signature.signature_id
    if parse_ok and typed_document is not None:
        # Document-level parse success without a LogicSignature still counts
        # as a structural signature check for non-frame notations.
        return True, ""
    return False, ""


# ---------------------------------------------------------------------------
# Gate implementation
# ---------------------------------------------------------------------------


class AdvisorExecutionGateV2:
    """Deterministic reparse gate for ErgoAI and SymbolicAI proposals.

    Interface owner: ``AdvisorProviderEvidence@2``.

    Never invokes ErgoAI or SymbolicAI runtimes.  Never elevates authority.
    Mock / availability / confidence / fluent text are audit-only signals.
    """

    INTERFACE: ClassVar[str] = ADVISOR_PROVIDER_EVIDENCE_V2_INTERFACE
    interface: ClassVar[str] = ADVISOR_PROVIDER_EVIDENCE_V2_INTERFACE
    VERSION: ClassVar[str] = ADVISOR_EXECUTION_V2_MODULE_VERSION
    TASK_ID: ClassVar[str] = ADVISOR_EXECUTION_V2_TASK_ID
    GOAL_ID: ClassVar[str] = ADVISOR_EXECUTION_V2_GOAL_ID

    def __init__(self) -> None:
        self._flogic = FLogicFrontendV2()
        self._advisor_parser = AdvisorCandidateParser()

    def execute(
        self,
        request: AdvisorExecutionRequestV2 | Mapping[str, Any],
    ) -> AdvisorExecutionResultV2:
        """Gate one typed advisor proposal through deterministic reparse."""

        req = (
            request
            if isinstance(request, AdvisorExecutionRequestV2)
            else AdvisorExecutionRequestV2.from_dict(request)
        )
        request_digest = _digest_of(req.to_dict())

        # Mock output can never establish any semantic claim; reject as a
        # mock-gated disposition while still emitting unverified evidence.
        if req.has_mock_output:
            reparse = AdvisorReparseRecord(
                disposition=AdvisorGateDisposition.MOCK_REJECTED,
                parse_ok=False,
                type_ok=False,
                signature_ok=False,
                features_ok=False,
                diagnostics=(
                    "mock_output_cannot_establish_parse_correctness",
                    "mock_output_cannot_establish_satisfiability",
                    "mock_output_cannot_establish_policy",
                    "mock_output_cannot_establish_proof",
                ),
            )
            return self._finalize(
                req,
                request_digest=request_digest,
                reparse=reparse,
            )

        if not req.proposed_source.strip():
            reparse = AdvisorReparseRecord(
                disposition=AdvisorGateDisposition.EMPTY_SOURCE,
                diagnostics=("empty_proposed_source",),
            )
            return self._finalize(
                req,
                request_digest=request_digest,
                reparse=reparse,
            )

        if is_ergoai_provider(req.provider):  # type: ignore[arg-type]
            return self._execute_ergoai(req, request_digest=request_digest)
        if is_symbolicai_provider(req.provider):  # type: ignore[arg-type]
            return self._execute_symbolicai(req, request_digest=request_digest)

        reparse = AdvisorReparseRecord(
            disposition=AdvisorGateDisposition.UNSUPPORTED_PROVIDER,
            diagnostics=(f"unsupported_provider:{req.provider}",),
        )
        return self._finalize(req, request_digest=request_digest, reparse=reparse)

    def gate_proposal_candidate(
        self,
        candidate: ProposalCandidate,
        *,
        request_id: str,
        provider: AdvisorProviderKind | str | None = None,
        notation: AdvisorNotation | str = AdvisorNotation.AUTO,
        features: Sequence[str] = (),
        available: bool = False,
        mock_output: Mapping[str, Any] | None = None,
        independently_validated: bool = False,
    ) -> AdvisorExecutionResultV2:
        """Gate a :class:`ProposalCandidate` through deterministic reparse."""

        request = AdvisorExecutionRequestV2.from_proposal_candidate(
            candidate,
            request_id=request_id,
            provider=provider,
            notation=notation,
            features=features,
            available=available,
            mock_output=mock_output,
            independently_validated=independently_validated,
        )
        return self.execute(request)

    # --- provider paths ----------------------------------------------------

    def _execute_ergoai(
        self,
        request: AdvisorExecutionRequestV2,
        *,
        request_digest: str,
    ) -> AdvisorExecutionResultV2:
        notation = (
            request.notation
            if isinstance(request.notation, AdvisorNotation)
            else normalize_notation(request.notation)
        )
        if notation not in {AdvisorNotation.FLOGIC, AdvisorNotation.AUTO}:
            reparse = AdvisorReparseRecord(
                disposition=AdvisorGateDisposition.PARSE_FAILED,
                parser_interface=FLOGIC_FRONTEND_V2_INTERFACE,
                logic_family=FLOGIC_V2_FAMILY_ID,
                logic_profile=FLOGIC_V2_PROFILE_ID,
                diagnostics=(
                    f"ergoai_requires_flogic_notation; got {notation.value}",
                ),
            )
            return self._finalize(
                request, request_digest=request_digest, reparse=reparse
            )

        result: FLogicFrontendV2Result = self._flogic.parse_text(
            request.proposed_source,
            document_id=f"doc:advisor:ergoai:{request.request_id}",
            request_id=f"req:advisor:ergoai:{request.request_id}",
            as_controlled_source=True,
        )
        if not result.ok:
            diags = tuple(
                f"{d.code}:{d.message}" for d in result.errors
            ) or ("flogic_v2_parse_failed",)
            reparse = AdvisorReparseRecord(
                disposition=AdvisorGateDisposition.PARSE_FAILED,
                parse_ok=False,
                type_ok=False,
                signature_ok=False,
                features_ok=False,
                parser_interface=FLOGIC_FRONTEND_V2_INTERFACE,
                logic_family=FLOGIC_V2_FAMILY_ID,
                logic_profile=FLOGIC_V2_PROFILE_ID,
                diagnostics=diags,
            )
            return self._finalize(
                request,
                request_digest=request_digest,
                reparse=reparse,
                typed_document=result.document,
                controlled_source=result.controlled_source,
            )

        expression = result.typed_expression
        signature = expression.signature if expression is not None else None
        discovered = _features_from_typed_expression(expression)
        if not discovered and result.document is not None:
            discovered = _features_from_document(
                result.document, AdvisorNotation.FLOGIC
            )
        features_ok, missing = _check_declared_features(
            request.features, discovered
        )
        sig_ok, sig_id = _signature_ok(
            signature, parse_ok=True, typed_document=result.document
        )

        if not sig_ok:
            disposition = AdvisorGateDisposition.SIGNATURE_FAILED
        elif not features_ok:
            disposition = AdvisorGateDisposition.FEATURE_MISMATCH
        else:
            disposition = AdvisorGateDisposition.TYPED_CANDIDATE

        reparse = AdvisorReparseRecord(
            disposition=disposition,
            parse_ok=True,
            type_ok=expression is not None,
            signature_ok=sig_ok,
            features_ok=features_ok,
            parser_interface=FLOGIC_FRONTEND_V2_INTERFACE,
            logic_family=FLOGIC_V2_FAMILY_ID,
            logic_profile=FLOGIC_V2_PROFILE_ID,
            discovered_features=discovered,
            missing_features=missing,
            signature_id=sig_id,
            expression_id=(
                expression.expression_id if expression is not None else ""
            ),
            expression_digest=(
                expression.content_digest if expression is not None else ""
            ),
            diagnostics=(
                ()
                if disposition is AdvisorGateDisposition.TYPED_CANDIDATE
                else (
                    *(f"missing_feature:{f}" for f in missing),
                    *(
                        ("signature_check_failed",)
                        if not sig_ok
                        else ()
                    ),
                )
            ),
            typed_kind="FLogicDocument",
        )
        return self._finalize(
            request,
            request_digest=request_digest,
            reparse=reparse,
            typed_expression=expression,
            typed_document=result.document,
            controlled_source=result.controlled_source,
            signature=signature,
        )

    def _execute_symbolicai(
        self,
        request: AdvisorExecutionRequestV2,
        *,
        request_digest: str,
    ) -> AdvisorExecutionResultV2:
        # Prefer FLogicFrontend@2 when the declared notation is frame logic so
        # ErgoAI/SymbolicAI frame proposals share the LFP2-013 artifact path.
        notation = (
            request.notation
            if isinstance(request.notation, AdvisorNotation)
            else normalize_notation(request.notation)
        )
        if notation is AdvisorNotation.FLOGIC:
            # Reuse ErgoAI path for frame-logic SymbolicAI proposals, but keep
            # the provider identity as SymbolicAI.
            ergo_like = AdvisorExecutionRequestV2(
                request_id=request.request_id,
                provider=AdvisorProviderKind.ERGOAI,
                proposed_source=request.proposed_source,
                source_ref_ids=request.source_ref_ids,
                notation=AdvisorNotation.FLOGIC,
                features=request.features,
                candidate_id=request.candidate_id,
                proposal_kind=request.proposal_kind,
                confidence=request.confidence,
                fluent_text=request.fluent_text,
                available=request.available,
                mock_output=None,
                independently_validated=request.independently_validated,
                metadata=dict(request.metadata),
            )
            inner = self._execute_ergoai(
                ergo_like, request_digest=request_digest
            )
            # Rebuild evidence under the original SymbolicAI provider.
            return self._finalize(
                request,
                request_digest=request_digest,
                reparse=inner.evidence.reparse,  # type: ignore[arg-type]
                typed_expression=inner.typed_expression,
                typed_document=inner.typed_document,
                controlled_source=inner.controlled_source,
                signature=inner.signature,
            )

        # Multi-notation path via AdvisorCandidateParser@1.
        proposal_provider = ProposalProvider.SYMAI
        candidate = ProposalCandidate(
            candidate_id=request.candidate_id,
            kind=request.proposal_kind,  # type: ignore[arg-type]
            body=request.proposed_source,
            source_ref_ids=request.source_ref_ids,
            provider=proposal_provider,
            confidence=request.confidence,
            rationale=request.fluent_text,
        )
        parse_result: AdvisorParseResult = self._advisor_parser.parse(
            candidate, notation=notation
        )
        parse_ok = bool(parse_result.parse_ok)
        typed_document = parse_result.typed_document
        resolved_notation = (
            parse_result.receipt.notation
            if isinstance(parse_result.receipt.notation, AdvisorNotation)
            else notation
        )
        discovered = _features_from_document(typed_document, resolved_notation)
        # Include family markers from the receipt.
        if parse_result.receipt.logic_family:
            family_token = re.sub(
                r"[^a-z0-9_]+",
                "_",
                parse_result.receipt.logic_family.lower(),
            ).strip("_")
            if family_token and _FEATURE_RE.fullmatch(family_token):
                discovered = tuple(sorted(set(discovered) | {family_token}))

        features_ok, missing = _check_declared_features(
            request.features, discovered if parse_ok else ()
        )
        sig_ok, sig_id = _signature_ok(
            None, parse_ok=parse_ok, typed_document=typed_document
        )

        if not parse_ok:
            disposition = AdvisorGateDisposition.PARSE_FAILED
        elif not sig_ok:
            disposition = AdvisorGateDisposition.SIGNATURE_FAILED
        elif not features_ok:
            disposition = AdvisorGateDisposition.FEATURE_MISMATCH
        else:
            disposition = AdvisorGateDisposition.TYPED_CANDIDATE

        diagnostics = list(parse_result.receipt.diagnostics)
        if missing:
            diagnostics.extend(f"missing_feature:{f}" for f in missing)
        if not sig_ok:
            diagnostics.append("signature_check_failed")

        reparse = AdvisorReparseRecord(
            disposition=disposition,
            parse_ok=parse_ok,
            type_ok=parse_ok and typed_document is not None,
            signature_ok=sig_ok if parse_ok else False,
            features_ok=features_ok if parse_ok else False,
            parser_interface=(
                parse_result.receipt.parser_interface
                or ADVISOR_CANDIDATE_PARSER_INTERFACE
            ),
            logic_family=str(parse_result.receipt.logic_family or ""),
            logic_profile="",
            discovered_features=discovered if parse_ok else (),
            missing_features=missing,
            signature_id=sig_id,
            diagnostics=tuple(diagnostics),
            typed_kind=str(parse_result.typed_kind or ""),
        )
        return self._finalize(
            request,
            request_digest=request_digest,
            reparse=reparse,
            typed_document=typed_document,
        )

    # --- finalize evidence -------------------------------------------------

    def _finalize(
        self,
        request: AdvisorExecutionRequestV2,
        *,
        request_digest: str,
        reparse: AdvisorReparseRecord,
        typed_expression: TypedExpression | None = None,
        typed_document: Any | None = None,
        controlled_source: ErgoAIControlledSourceV2 | None = None,
        signature: LogicSignature | None = None,
    ) -> AdvisorExecutionResultV2:
        # Independent validation is never inferred from reparse alone.
        independently_validated = bool(request.independently_validated)
        # ProposalCandidate only admits leanstral/symai providers; ErgoAI
        # proposals use a symai-shaped candidate for the acceptance helper
        # while evidence retains the real provider identity.
        acceptance_body = (
            request.proposed_source
            if request.proposed_source.strip()
            else "unparsed_empty_proposal"
        )
        acceptance = accept_candidate(
            ProposalCandidate(
                candidate_id=request.candidate_id,
                kind=request.proposal_kind,  # type: ignore[arg-type]
                body=acceptance_body,
                source_ref_ids=request.source_ref_ids,
                provider=ProposalProvider.SYMAI,
                confidence=request.confidence,
            ),
            compiled=reparse.reparse_succeeded,
            independently_validated=independently_validated,
            reasons=(
                ()
                if reparse.reparse_succeeded
                else ("deterministic_reparse_or_feature_check_failed",)
            ),
        )

        # Hard invariant: non-deterministic signals never establish claims.
        for claim in AdvisorClaimKind:
            if non_deterministic_signal_establishes(
                claim,
                confidence=request.confidence,
                fluent_text=request.fluent_text or None,
                available=request.available,
                mock_output=request.mock_output,
            ):
                raise AdvisorAuthorityError(
                    f"non-deterministic signal incorrectly established {claim.value}"
                )

        evidence = AdvisorProviderEvidenceV2(
            evidence_id=f"ev:advisor:{request.request_id}",
            request_id=request.request_id,
            request_digest=request_digest,
            provider=request.provider,  # type: ignore[arg-type]
            reparse=reparse,
            candidate_id=request.candidate_id,
            source_ref_ids=request.source_ref_ids,
            source_digest=request.source_digest,
            authority=UNVERIFIED_AUTHORITY,
            result_authority=ResultAuthority.CANDIDATE,
            result_status=ResultStatus.CANDIDATE,
            role=ToolRole.ADVISOR,
            authority_ceiling=ToolchainAuthorityCeiling.ADVISORY,
            confidence=request.confidence,
            fluent_text_present=bool(request.fluent_text.strip()),
            available=request.available,
            mock_output_present=request.has_mock_output,
            independently_validated=independently_validated,
            acceptance=acceptance,
            metadata={
                "task_id": ADVISOR_EXECUTION_V2_TASK_ID,
                "goal_id": ADVISOR_EXECUTION_V2_GOAL_ID,
                "lane": ADVISOR_LANE_ID,
                "evidence_kind": ADVISOR_EVIDENCE_KIND,
                "controlled_source_interface": (
                    ERGOAI_CONTROLLED_SOURCE_V2_INTERFACE
                    if controlled_source is not None
                    else ""
                ),
                "family": reparse.logic_family or "",
            },
        )
        return AdvisorExecutionResultV2(
            request=request,
            evidence=evidence,
            typed_expression=typed_expression,
            typed_document=typed_document,
            controlled_source=controlled_source,
            signature=signature,
        )


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def gate_advisor_proposal(
    request: AdvisorExecutionRequestV2 | Mapping[str, Any],
) -> AdvisorExecutionResultV2:
    """Module-level convenience for :class:`AdvisorExecutionGateV2`."""

    return AdvisorExecutionGateV2().execute(request)


def gate_ergoai_proposal(
    proposed_source: str,
    *,
    request_id: str,
    source_ref_ids: Sequence[str],
    features: Sequence[str] = (),
    confidence: float = 0.0,
    fluent_text: str = "",
    available: bool = False,
    mock_output: Mapping[str, Any] | None = None,
    independently_validated: bool = False,
    candidate_id: str = "",
) -> AdvisorExecutionResultV2:
    """Gate an ErgoAI F-logic proposal through ``FLogicFrontend@2``."""

    request = AdvisorExecutionRequestV2(
        request_id=request_id,
        provider=AdvisorProviderKind.ERGOAI,
        proposed_source=proposed_source,
        source_ref_ids=tuple(source_ref_ids),
        notation=AdvisorNotation.FLOGIC,
        features=tuple(features),
        candidate_id=candidate_id,
        confidence=confidence,
        fluent_text=fluent_text,
        available=available,
        mock_output=mock_output,
        independently_validated=independently_validated,
    )
    return AdvisorExecutionGateV2().execute(request)


def gate_symbolicai_proposal(
    proposed_source: str,
    *,
    request_id: str,
    source_ref_ids: Sequence[str],
    notation: AdvisorNotation | str = AdvisorNotation.AUTO,
    features: Sequence[str] = (),
    confidence: float = 0.0,
    fluent_text: str = "",
    available: bool = False,
    mock_output: Mapping[str, Any] | None = None,
    independently_validated: bool = False,
    candidate_id: str = "",
    provider: AdvisorProviderKind | str = AdvisorProviderKind.SYMBOLICAI,
) -> AdvisorExecutionResultV2:
    """Gate a SymbolicAI / SymAI proposal through deterministic reparse."""

    request = AdvisorExecutionRequestV2(
        request_id=request_id,
        provider=provider,
        proposed_source=proposed_source,
        source_ref_ids=tuple(source_ref_ids),
        notation=notation,
        features=tuple(features),
        candidate_id=candidate_id,
        confidence=confidence,
        fluent_text=fluent_text,
        available=available,
        mock_output=mock_output,
        independently_validated=independently_validated,
    )
    return AdvisorExecutionGateV2().execute(request)


__all__ = [
    "ADVISOR_EXECUTION_REQUEST_SCHEMA",
    "ADVISOR_EXECUTION_REQUEST_V2_INTERFACE",
    "ADVISOR_EXECUTION_RESULT_SCHEMA",
    "ADVISOR_EXECUTION_RESULT_V2_INTERFACE",
    "ADVISOR_EXECUTION_V2_GOAL_ID",
    "ADVISOR_EXECUTION_V2_MODULE_VERSION",
    "ADVISOR_EXECUTION_V2_TASK_ID",
    "ADVISOR_PROVIDER_EVIDENCE_SCHEMA",
    "ADVISOR_PROVIDER_EVIDENCE_V2_INTERFACE",
    "ADVISOR_REPARSE_RECORD_SCHEMA",
    "AdvisorAuthorityError",
    "AdvisorClaimKind",
    "AdvisorExecutionError",
    "AdvisorExecutionGateV2",
    "AdvisorExecutionRequestV2",
    "AdvisorExecutionResultV2",
    "AdvisorGateDisposition",
    "AdvisorProviderEvidenceV2",
    "AdvisorProviderKind",
    "AdvisorReparseRecord",
    "advisor_never_establishes_proof",
    "gate_advisor_proposal",
    "gate_ergoai_proposal",
    "gate_symbolicai_proposal",
    "is_ergoai_provider",
    "is_symbolicai_provider",
    "non_deterministic_signal_establishes",
    "normalize_advisor_provider",
    "provider_logic_identity",
]
