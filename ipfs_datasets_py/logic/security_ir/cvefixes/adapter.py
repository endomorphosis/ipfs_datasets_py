"""Convert CVEfixes policy candidates into canonical Security IR declarations.

The adapter is intentionally a declaration boundary, not a promotion path.
An observed, validated, or reviewed candidate can be represented as a
``Policy(effect=DENY)``, but the resulting declaration explicitly remains
non-authoritative.  Evaluation verdicts and other result state stay attached
to the detached candidate record and are never copied into Security IR.

Round-tripping is provided by :class:`CVEfixesAdapterResult`, which retains the
exact canonical source records, candidate, and review binding alongside the
declaration.  This avoids hiding lossy conversion in declaration attributes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
import re
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)
from ..model import (
    Policy,
    PolicyEffect,
    Resource,
    SecurityClaim,
    SecurityIR,
    SecuritySource,
    StateMachine,
    StateTransition,
    ThreatAssumption,
)
from .schemas import PolicyCandidate, SourceRecord
from .vocabulary import (
    CVEFIXES_POLICY_ATTRIBUTES_KEY,
    CVEfixesPolicyAttributes,
    CVEfixesVocabularyError,
)


CVEFIXES_ADAPTER_VERSION: Final = "cvefixes-security-ir-adapter/v1"
CVEFIXES_ADAPTER_ATTRIBUTES_KEY: Final = "security.cvefixes.adapter"
_STABLE_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_WILDCARD_RE: Final = re.compile(r"[*?\[\]{}]")
_GENERALIZATION_KEYS: Final = frozenset(
    {
        "generalized",
        "generalized_scope",
        "is_generalized",
        "scope_kind",
        "scope_mode",
    }
)
_GENERALIZATION_VALUES: Final = frozenset(
    {"generalized", "glob", "pattern", "regex", "wildcard"}
)
_AUTHORITY_KEYS: Final = frozenset(
    {
        "authoritative",
        "authoritative_policy",
        "grants_authority",
        "grants_execution_authority",
        "permits_execution",
        "proof_authoritative",
    }
)
_POLICY_ATTRIBUTE_FIELDS: Final = frozenset(
    {
        "action",
        "cve_ids",
        "cwe_ids",
        "effects",
        "language",
        "mitigations",
        "preconditions",
        "schema_version",
        "scope",
    }
)


class CVEfixesAdapterError(ValueError):
    """Raised when a candidate cannot be represented without broadening it."""


class CandidateReviewState(str, Enum):
    """Non-authoritative lifecycle states accepted by the adapter."""

    OBSERVED_CANDIDATE = "observed_candidate"
    VALIDATED_CANDIDATE = "validated_candidate"
    REVIEWED_PATTERN = "reviewed_pattern"


# A descriptive alias for callers that use the domain-qualified spelling.
CVEfixesReviewState = CandidateReviewState


def _stable_id(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or _STABLE_ID_RE.fullmatch(value) is None:
        raise CVEfixesAdapterError(f"{name} must be a stable identifier")
    return value


def _string(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise CVEfixesAdapterError(f"{name} must be a string")
    if value != value.strip() or "\x00" in value:
        raise CVEfixesAdapterError(f"{name} must be canonical text")
    if not allow_empty and not value:
        raise CVEfixesAdapterError(f"{name} must not be empty")
    return value


def _strict_json_object(value: str | bytes | bytearray) -> Mapping[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise CVEfixesAdapterError(f"duplicate JSON key: {key!r}")
            result[key] = item
        return result

    def reject_constant(constant: str) -> Any:
        raise CVEfixesAdapterError(f"non-finite JSON number: {constant}")

    try:
        decoded = json.loads(
            value,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except CVEfixesAdapterError:
        raise
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise CVEfixesAdapterError("adapter result is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise CVEfixesAdapterError("adapter result JSON must be an object")
    return decoded


def _contains_generalization(value: Any, *, key: str = "") -> bool:
    """Detect explicit or wildcard broadening without interpreting regexes."""

    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            normalized_key = str(raw_key).casefold()
            if normalized_key in _GENERALIZATION_KEYS:
                if item is True:
                    return True
                if isinstance(item, str) and (
                    item.casefold() in _GENERALIZATION_VALUES
                ):
                    return True
            if _contains_generalization(item, key=normalized_key):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(_contains_generalization(item, key=key) for item in value)
    if isinstance(value, str):
        if _WILDCARD_RE.search(value):
            return True
        return key in _GENERALIZATION_KEYS and (
            value.casefold() in _GENERALIZATION_VALUES
        )
    return False


def _assert_no_authority_claim(value: Any, *, path: str = "candidate") -> None:
    """Reject attempts to smuggle an authority/result grant into a candidate."""

    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.casefold()
            child_path = f"{path}.{key}"
            if normalized in _AUTHORITY_KEYS and (
                item is True
                or (
                    isinstance(item, str)
                    and item.casefold()
                    not in {"", "false", "none", "non_authoritative", "candidate"}
                )
            ):
                raise CVEfixesAdapterError(
                    f"{child_path} cannot claim policy or execution authority"
                )
            if normalized == "authority" and isinstance(item, str) and (
                item.casefold()
                not in {"candidate", "non_authoritative", "observed_candidate"}
            ):
                raise CVEfixesAdapterError(
                    f"{child_path} cannot broaden candidate authority"
                )
            _assert_no_authority_claim(item, path=child_path)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            _assert_no_authority_claim(item, path=f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class CandidateReview:
    """Explicit review binding kept separate from evaluation result state."""

    state: CandidateReviewState
    review_id: str = ""
    reviewer_id: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)

    # Review metadata describes provenance; it never grants authority.
    grants_execution_authority: ClassVar[bool] = False

    def __post_init__(self) -> None:
        try:
            state = (
                self.state
                if isinstance(self.state, CandidateReviewState)
                else CandidateReviewState(self.state)
            )
        except (TypeError, ValueError) as exc:
            raise CVEfixesAdapterError(
                f"unsupported candidate review state: {self.state!r}"
            ) from exc
        object.__setattr__(self, "state", state)
        _stable_id(self.review_id, "review_id", allow_empty=True)
        _stable_id(self.reviewer_id, "reviewer_id", allow_empty=True)
        if state is CandidateReviewState.REVIEWED_PATTERN and (
            not self.review_id or not self.reviewer_id
        ):
            raise CVEfixesAdapterError(
                "reviewed_pattern requires review_id and reviewer_id"
            )
        try:
            attributes = freeze_json_mapping(self.attributes)
        except ProvenanceValidationError as exc:
            raise CVEfixesAdapterError(f"review attributes: {exc}") from exc
        _assert_no_authority_claim(attributes, path="review.attributes")
        object.__setattr__(self, "attributes", attributes)

    @property
    def explicitly_reviewed(self) -> bool:
        return self.state is CandidateReviewState.REVIEWED_PATTERN

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": thaw_json(self.attributes),
            "grants_execution_authority": False,
            "review_id": self.review_id,
            "reviewer_id": self.reviewer_id,
            "state": self.state.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateReview":
        if not isinstance(value, Mapping):
            raise CVEfixesAdapterError("candidate review must be a mapping")
        expected = {
            "attributes",
            "grants_execution_authority",
            "review_id",
            "reviewer_id",
            "state",
        }
        if set(value) != expected:
            raise CVEfixesAdapterError(
                "candidate review fields are not canonical"
            )
        if value["grants_execution_authority"] is not False:
            raise CVEfixesAdapterError(
                "candidate review cannot grant execution authority"
            )
        return cls(
            state=value["state"],
            review_id=value["review_id"],
            reviewer_id=value["reviewer_id"],
            attributes=value["attributes"],
        )


def _policy_attributes(candidate: PolicyCandidate) -> CVEfixesPolicyAttributes:
    scope = thaw_json(candidate.scope)
    raw: Any
    if CVEFIXES_POLICY_ATTRIBUTES_KEY in scope:
        raw = scope[CVEFIXES_POLICY_ATTRIBUTES_KEY]
    elif "policy_attributes" in scope:
        raw = scope["policy_attributes"]
    else:
        raw = {key: scope[key] for key in _POLICY_ATTRIBUTE_FIELDS if key in scope}
    try:
        attributes = CVEfixesPolicyAttributes.from_dict(raw)
        return attributes.require_exact_policy_constraints()
    except (CVEfixesVocabularyError, TypeError, KeyError) as exc:
        raise CVEfixesAdapterError(
            "candidate scope must contain complete, exact CVEfixes policy "
            "attributes"
        ) from exc


def _source_id(source: SourceRecord) -> str:
    return f"source:cvefixes:{source.digest}"


def _candidate_prefix(candidate: PolicyCandidate) -> str:
    return f"cvefixes:{candidate.digest}"


def _validate_sources(
    candidate: PolicyCandidate, sources: Sequence[SourceRecord]
) -> tuple[SourceRecord, ...]:
    if isinstance(sources, (str, bytes, bytearray)) or not isinstance(
        sources, Sequence
    ):
        raise CVEfixesAdapterError("sources must be a sequence")
    normalized = tuple(sources)
    if not normalized:
        raise CVEfixesAdapterError("at least one source record is mandatory")
    if any(not isinstance(item, SourceRecord) for item in normalized):
        raise CVEfixesAdapterError("sources must contain SourceRecord values")
    if len({item.cid for item in normalized}) != len(normalized):
        raise CVEfixesAdapterError("source records must be unique")

    represented: set[str] = set()
    for source in normalized:
        represented.add(source.cid)
        represented.update(source.source_cids)
    missing = sorted(set(candidate.source_cids) - represented)
    if missing:
        raise CVEfixesAdapterError(
            "candidate source_cids are not covered by supplied source records: "
            + ", ".join(missing)
        )
    return tuple(sorted(normalized, key=lambda item: item.cid))


def _source_declaration(
    source: SourceRecord, review: CandidateReview
) -> SecuritySource:
    content_sha256 = source.payload.get("content_sha256", "")
    if not isinstance(content_sha256, str):
        raise CVEfixesAdapterError("source content_sha256 must be a string")
    return SecuritySource(
        source_id=_source_id(source),
        uri=source.source_uri,
        revision=source.source_revision,
        content_sha256=content_sha256,
        review_status=review.state.value,
        attributes={
            "adapter_version": CVEFIXES_ADAPTER_VERSION,
            "config_cid": source.config_cid,
            "grants_execution_authority": False,
            "row_key": source.row_key,
            "source_record_cid": source.cid,
        },
    )


def _adapter_attributes(
    candidate: PolicyCandidate,
    review: CandidateReview,
    *,
    generalized: bool,
) -> dict[str, Any]:
    return {
        "adapter_version": CVEFIXES_ADAPTER_VERSION,
        "candidate_cid": candidate.cid,
        "candidate_scope": thaw_json(candidate.scope),
        "generalized_scope": generalized,
        "grants_execution_authority": False,
        "requires_authoritative_adoption": True,
        "review": review.to_dict(),
    }


def _state_machine(
    candidate: PolicyCandidate,
    source_ids: tuple[str, ...],
    adapter_attributes: Mapping[str, Any],
) -> StateMachine | None:
    raw = candidate.payload.get("state_machine")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise CVEfixesAdapterError("state_machine must be a mapping")
    allowed = {"initial_state", "states", "transitions"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise CVEfixesAdapterError(
            "unknown state_machine field(s): " + ", ".join(unknown)
        )
    transitions_raw = raw.get("transitions", ())
    if isinstance(transitions_raw, (str, bytes, bytearray)) or not isinstance(
        transitions_raw, Sequence
    ):
        raise CVEfixesAdapterError("state_machine transitions must be a sequence")
    transitions: list[StateTransition] = []
    for item in transitions_raw:
        if not isinstance(item, Mapping):
            raise CVEfixesAdapterError(
                "state_machine transitions must contain mappings"
            )
        allowed_transition = {
            "attributes",
            "effect",
            "event",
            "guard",
            "source_state",
            "target_state",
        }
        if set(item) - allowed_transition:
            raise CVEfixesAdapterError(
                "state_machine transition contains unknown fields"
            )
        transitions.append(StateTransition.from_dict(item))
    return StateMachine(
        state_machine_id=f"state-machine:{_candidate_prefix(candidate)}",
        states=tuple(raw.get("states", ())),
        initial_state=raw.get("initial_state", ""),
        transitions=tuple(transitions),
        source_ids=source_ids,
        attributes=dict(adapter_attributes),
    )


@dataclass(frozen=True, slots=True)
class CVEfixesAdapterResult:
    """Loss-aware conversion result with detached canonical inputs."""

    declaration: SecurityIR
    candidate: PolicyCandidate
    sources: tuple[SourceRecord, ...]
    review: CandidateReview
    adapter_version: str = CVEFIXES_ADAPTER_VERSION

    proof_authoritative: ClassVar[bool] = False
    grants_execution_authority: ClassVar[bool] = False
    authority: ClassVar[str] = "candidate"

    def __post_init__(self) -> None:
        if not isinstance(self.declaration, SecurityIR):
            raise CVEfixesAdapterError("declaration must be SecurityIR")
        if not isinstance(self.candidate, PolicyCandidate):
            raise CVEfixesAdapterError("candidate must be PolicyCandidate")
        if not isinstance(self.review, CandidateReview):
            raise CVEfixesAdapterError("review must be CandidateReview")
        normalized_sources = _validate_sources(self.candidate, self.sources)
        object.__setattr__(self, "sources", normalized_sources)
        if self.adapter_version != CVEFIXES_ADAPTER_VERSION:
            raise CVEfixesAdapterError(
                f"unsupported adapter version: {self.adapter_version!r}"
            )

    @property
    def candidate_round_trip(self) -> PolicyCandidate:
        """Return the exact immutable candidate supplied to the adapter."""

        return self.candidate

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_version": self.adapter_version,
            "candidate": self.candidate.to_dict(),
            "declaration": self.declaration.to_dict(),
            "review": self.review.to_dict(),
            "sources": [source.to_dict() for source in self.sources],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CVEfixesAdapterResult":
        if not isinstance(value, Mapping):
            raise CVEfixesAdapterError("adapter result must be a mapping")
        expected = {
            "adapter_version",
            "candidate",
            "declaration",
            "review",
            "sources",
        }
        if set(value) != expected:
            raise CVEfixesAdapterError("adapter result fields are not canonical")
        if value["adapter_version"] != CVEFIXES_ADAPTER_VERSION:
            raise CVEfixesAdapterError(
                f"unsupported adapter version: {value['adapter_version']!r}"
            )
        candidate = PolicyCandidate.from_dict(value["candidate"])
        review = CandidateReview.from_dict(value["review"])
        sources_raw = value["sources"]
        if isinstance(sources_raw, (str, bytes, bytearray)) or not isinstance(
            sources_raw, Sequence
        ):
            raise CVEfixesAdapterError("sources must be a sequence")
        sources = tuple(SourceRecord.from_dict(item) for item in sources_raw)
        declaration = SecurityIR.from_dict(value["declaration"])
        rebuilt = adapt_cvefixes_candidate(
            candidate,
            sources=sources,
            review=review,
            declaration_id=declaration.declaration_id,
        )
        if rebuilt.declaration.to_dict() != declaration.to_dict():
            raise CVEfixesAdapterError(
                "declaration does not match its candidate/source/review binding"
            )
        return rebuilt

    @classmethod
    def from_json(
        cls, value: str | bytes | bytearray
    ) -> "CVEfixesAdapterResult":
        return cls.from_dict(_strict_json_object(value))


def adapt_cvefixes_candidate(
    candidate: PolicyCandidate,
    *,
    sources: Sequence[SourceRecord],
    review: CandidateReview,
    declaration_id: str | None = None,
) -> CVEfixesAdapterResult:
    """Adapt one grounded CVEfixes candidate without promoting its authority."""

    if not isinstance(candidate, PolicyCandidate):
        raise CVEfixesAdapterError("candidate must be PolicyCandidate")
    if not isinstance(review, CandidateReview):
        raise CVEfixesAdapterError("review state is mandatory")
    normalized_sources = _validate_sources(candidate, sources)
    if candidate.effect != PolicyEffect.DENY.value:
        raise CVEfixesAdapterError(
            "only deny candidates can become CVEfixes Security IR policies"
        )
    _assert_no_authority_claim(candidate.scope, path="candidate.scope")
    _assert_no_authority_claim(candidate.payload, path="candidate.payload")

    generalized = _contains_generalization(candidate.scope)
    if generalized and not review.explicitly_reviewed:
        raise CVEfixesAdapterError(
            "wildcard or generalized scopes require explicit reviewed_pattern "
            "provenance"
        )
    attributes = _policy_attributes(candidate)
    prefix = _candidate_prefix(candidate)
    source_ids = tuple(_source_id(source) for source in normalized_sources)
    adapter_attributes = _adapter_attributes(
        candidate, review, generalized=generalized
    )

    resource = Resource(
        resource_id=f"resource:{prefix}",
        kind=attributes.scope.name,
        source_ids=source_ids,
        attributes={
            **adapter_attributes,
            "language": (
                attributes.language.canonical
                if attributes.language is not None
                else None
            ),
            "scope": attributes.scope.canonical,
        },
    )
    policy = Policy(
        policy_id=f"policy:{prefix}",
        name=f"CVEfixes deny candidate {candidate.cid}",
        effect=PolicyEffect.DENY,
        resource_ids=(resource.resource_id,),
        source_ids=source_ids,
        attributes={
            CVEFIXES_POLICY_ATTRIBUTES_KEY: attributes.to_dict(),
            CVEFIXES_ADAPTER_ATTRIBUTES_KEY: adapter_attributes,
        },
    )
    assumptions = tuple(
        ThreatAssumption(
            assumption_id=f"assumption:{prefix}:{index}",
            statement=f"Candidate precondition {term.canonical}",
            source_ids=source_ids,
            attributes={
                **adapter_attributes,
                "precondition": term.canonical,
            },
        )
        for index, term in enumerate(attributes.preconditions, start=1)
    )
    effects = ", ".join(term.canonical for term in attributes.effects)
    claim = SecurityClaim(
        claim_id=f"claim:{prefix}",
        statement=(
            f"The action {attributes.action.canonical} must not produce "
            f"{effects} in scope {attributes.scope.canonical}"
        ),
        domain="security.cvefixes",
        severity=_string(
            candidate.payload.get("severity", "unspecified"),
            "candidate severity",
        ),
        assumption_ids=tuple(item.assumption_id for item in assumptions),
        policy_ids=(policy.policy_id,),
        source_ids=source_ids,
        attributes={
            **adapter_attributes,
            "expected_invariant": "forbidden_action_effect_absent",
        },
    )
    machine = _state_machine(
        candidate, source_ids, MappingProxyType(adapter_attributes)
    )
    resolved_declaration_id = (
        _stable_id(declaration_id, "declaration_id")
        if declaration_id is not None
        else f"security-ir:{prefix}"
    )
    declaration = SecurityIR(
        declaration_id=resolved_declaration_id,
        resources=(resource,),
        policies=(policy,),
        state_machines=(machine,) if machine is not None else (),
        assumptions=assumptions,
        claims=(claim,),
        sources=tuple(
            _source_declaration(source, review)
            for source in normalized_sources
        ),
    )
    return CVEfixesAdapterResult(
        declaration=declaration,
        candidate=candidate,
        sources=normalized_sources,
        review=review,
    )


class CVEfixesSecurityIRAdapter:
    """Small stateless object API for dependency-injected adapter call sites."""

    def adapt(
        self,
        candidate: PolicyCandidate,
        *,
        sources: Sequence[SourceRecord],
        review: CandidateReview,
        declaration_id: str | None = None,
    ) -> CVEfixesAdapterResult:
        return adapt_cvefixes_candidate(
            candidate,
            sources=sources,
            review=review,
            declaration_id=declaration_id,
        )


def to_cvefixes_candidate(result: CVEfixesAdapterResult) -> PolicyCandidate:
    """Recover the exact candidate from a loss-aware adapter result."""

    if not isinstance(result, CVEfixesAdapterResult):
        raise CVEfixesAdapterError("result must be CVEfixesAdapterResult")
    return result.candidate_round_trip


# Functional spelling consistent with the package's other adapters.
adapt_cvefixes_security_ir = adapt_cvefixes_candidate


__all__ = [
    "CVEFIXES_ADAPTER_ATTRIBUTES_KEY",
    "CVEFIXES_ADAPTER_VERSION",
    "CVEfixesAdapterError",
    "CVEfixesAdapterResult",
    "CVEfixesReviewState",
    "CVEfixesSecurityIRAdapter",
    "CandidateReview",
    "CandidateReviewState",
    "adapt_cvefixes_candidate",
    "adapt_cvefixes_security_ir",
    "to_cvefixes_candidate",
]
