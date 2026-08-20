"""Build test, proof, policy, and capsule adequacy profiles (AAE-029).

Interface surface:

* ``build_test_adequacy_profile@1`` — seal a ``TestAdequacyProfile@1`` from
  claim, reachable-behavior, detector, false-assurance, uncertainty, gap, and
  scope bindings for the test surface.
* ``build_proof_adequacy_profile@1`` — seal a ``ProofAdequacyProfile@1`` for
  formal proof / obligation surfaces.
* ``build_policy_adequacy_profile@1`` — seal a ``PolicyAdequacyProfile@1`` for
  policy / constraint surfaces.
* ``build_capsule_adequacy_profile@1`` — seal a ``CapsuleAdequacyProfile@1`` for
  semantic-capsule completeness surfaces.

Authority rules (normative):

* Pure and deterministic: no store, worktree, or production-policy mutation.
* Canonical identity comes only from ``software_contracts.content``.
* Profiles bind claims, reachable behavior, detectors, false-assurance
  evidence, uncertainty, gaps, and scope.
* A mutation, kill, coverage, or composite **score never establishes
  correctness** and never upgrades a profile to ``adequate``.
* Incomplete observation fails closed.
* Closed gap and verdict taxonomies fail closed on unknowns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import re
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceArtifactHeader,
    AssuranceBaseError,
    GeneratorIdentity,
    VersionBinding,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.analysis_contracts import (
    AdequacyVerdict,
    AnalysisContractError,
    CapsuleAdequacyGapClass,
    CapsuleAdequacyProfile,
    MinimizedEvidenceBinding,
    PolicyAdequacyGapClass,
    PolicyAdequacyProfile,
    ProofAdequacyGapClass,
    ProofAdequacyProfile,
    SourceSpan,
    TestAdequacyGapClass,
    TestAdequacyProfile,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

BUILD_TEST_ADEQUACY_PROFILE_INTERFACE: Final[str] = "build_test_adequacy_profile@1"
BUILD_PROOF_ADEQUACY_PROFILE_INTERFACE: Final[str] = "build_proof_adequacy_profile@1"
BUILD_POLICY_ADEQUACY_PROFILE_INTERFACE: Final[str] = "build_policy_adequacy_profile@1"
BUILD_CAPSULE_ADEQUACY_PROFILE_INTERFACE: Final[str] = (
    "build_capsule_adequacy_profile@1"
)

ADEQUACY_CLAIM_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-adequacy-claim-binding@1"
)
REACHABLE_BEHAVIOR_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-reachable-behavior-binding@1"
)
DETECTOR_ADEQUACY_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-detector-adequacy-binding@1"
)
FALSE_ASSURANCE_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-false-assurance-evidence@1"
)
UNCERTAINTY_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-uncertainty-binding@1"
)
ADEQUACY_SCOPE_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-adequacy-scope-binding@1"
)
TEST_ADEQUACY_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-test-adequacy-subject@1"
)
PROOF_ADEQUACY_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-proof-adequacy-subject@1"
)
POLICY_ADEQUACY_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-policy-adequacy-subject@1"
)
CAPSULE_ADEQUACY_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-capsule-adequacy-subject@1"
)
ADEQUACY_PROFILE_BUILD_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-adequacy-profile-build-result@1"
)
ADEQUACY_PROFILE_BUILD_RESULT_INTERFACE: Final[str] = "AdequacyProfileBuildResult@1"

GENERATOR_ID: Final[str] = "adequacy_profiles"
GENERATOR_VERSION: Final[str] = "1.0.0"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_LIST: Final[int] = 1_024
MAX_CLAIMS: Final[int] = 1_024
MAX_BEHAVIORS: Final[int] = 1_024
MAX_DETECTORS: Final[int] = 1_024
MAX_EVIDENCE: Final[int] = 1_024
MAX_UNCERTAINTY: Final[int] = 256
MAX_GAPS: Final[int] = 256
MAX_SPANS: Final[int] = 256

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)

# Keys that attempt to convert a numeric or composite score into correctness.
# Presence as authority fails closed (acceptance: never convert a score into
# correctness).
SCORE_AUTHORITY_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "adequacy_from_score",
        "composite_score_authority",
        "coverage_percent_authority",
        "coverage_score",
        "kill_rate",
        "kill_score",
        "mutation_score",
        "mutation_score_authority",
        "score_establishes_adequacy",
        "score_establishes_correctness",
        "score_proves_correctness",
    }
)

# Surface kinds admitted by build results.
_SURFACE_KINDS: Final[frozenset[str]] = frozenset(
    {"test", "proof", "policy", "capsule"}
)


class AdequacyError(AssuranceBaseError):
    """Raised when adequacy profile construction fails closed."""


class DetectorAdequacyRole(str, Enum):
    """Closed roles for detectors bound into an adequacy subject."""

    COVERED = "covered"
    MISSING = "missing"
    PREDICTED = "predicted"
    OPTIONAL = "optional"
    OMITTED = "omitted"


class UncertaintyKind(str, Enum):
    """Closed uncertainty kinds that may block or qualify adequacy."""

    INCOMPLETE_OBSERVATION = "incomplete_observation"
    UNKNOWN_DETECTOR = "unknown_detector"
    AMBIGUOUS_CLAIM = "ambiguous_claim"
    UNBOUNDED_SCOPE = "unbounded_scope"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    SCORE_ONLY_SIGNAL = "score_only_signal"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    OTHER = "other"


class FalseAssuranceEvidenceKind(str, Enum):
    """Closed kinds of evidence that current assurance accepted incorrectly."""

    SURVIVING_MUTANT = "surviving_mutant"
    VACUITY_FINDING = "vacuity_finding"
    DETECTION_FAILURE = "detection_failure"
    ASSURANCE_GAP = "assurance_gap"
    EQUIVALENCE_DISPUTE = "equivalence_dispute"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise AdequacyError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise AdequacyError(
            f"{name} must be NFC-normalized and free of leading/trailing whitespace"
        )
    if len(value) > maximum:
        raise AdequacyError(f"{name} exceeds maximum length")
    if any(not char.isprintable() for char in value):
        raise AdequacyError(f"{name} contains non-printable characters")
    reject_private_model_authority_and_host_fallbacks({name: value}, path=name)
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise AdequacyError(f"{name} must be a boolean")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise AdequacyError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise AdequacyError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    text = _text(value, name)
    try:
        validate_cid(text)
    except Exception as exc:  # pragma: no cover - validate_cid raises ValueError
        raise AdequacyError(f"{name} must be a valid CIDv1") from exc
    return text


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    if type(value) is str:
        try:
            return enum_type(value).value
        except ValueError as exc:
            raise AdequacyError(
                f"{name}={value!r} is not an admitted {enum_type.__name__}"
            ) from exc
    raise AdequacyError(f"{name} must be {enum_type.__name__} or string")


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise AdequacyError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise AdequacyError(
            f"{name} field set mismatch; missing={missing}; extra={extra}"
        )
    return dict(data)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AdequacyError(f"{name} must be a mapping")
    reject_private_model_authority_and_host_fallbacks(value, path=name)
    validate_structured_value(value)
    _reject_score_authority(value, name)
    return MappingProxyType(_thaw_structured(value))


def _sealed_profile_mapping(value: Any, name: str) -> Mapping[str, Any]:
    """Validate a nested sealed adequacy profile dict.

    Sealed profiles already carry artifact headers with fields such as
    ``environment_cid``. Host-fallback key rejection therefore cannot be
    applied recursively to nested sealed profiles; structured identity and
    score-authority checks still apply.
    """

    if not isinstance(value, Mapping):
        raise AdequacyError(f"{name} must be a mapping")
    validate_structured_value(value)
    _reject_score_authority(value, name)
    return MappingProxyType(_thaw_structured(value))


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_LIST,
    symbol: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AdequacyError(f"{name} must be a list")
    if len(values) > maximum:
        raise AdequacyError(f"{name} exceeds maximum length")
    seen: set[str] = set()
    out: list[str] = []
    for index, raw in enumerate(values):
        item = (
            _symbol_id(raw, f"{name}[{index}]")
            if symbol
            else _token(raw, f"{name}[{index}]")
        )
        if item in seen:
            raise AdequacyError(f"{name} must not contain duplicates")
        seen.add(item)
        out.append(item)
    return tuple(sorted(out))


def _unique_sorted_cids(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AdequacyError(f"{name} must be a list")
    if len(values) > maximum:
        raise AdequacyError(f"{name} exceeds maximum length")
    seen: set[str] = set()
    out: list[str] = []
    for index, raw in enumerate(values):
        item = _cid(raw, f"{name}[{index}]")
        if item in seen:
            raise AdequacyError(f"{name} must not contain duplicates")
        seen.add(item)
        out.append(item)
    return tuple(sorted(out))


def _unique_sorted_texts(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AdequacyError(f"{name} must be a list")
    if len(values) > maximum:
        raise AdequacyError(f"{name} exceeds maximum length")
    seen: set[str] = set()
    out: list[str] = []
    for index, raw in enumerate(values):
        item = _text(raw, f"{name}[{index}]")
        if item in seen:
            raise AdequacyError(f"{name} must not contain duplicates")
        seen.add(item)
        out.append(item)
    return tuple(sorted(out))


def _reject_score_authority(value: Mapping[str, Any], path: str) -> None:
    """Fail closed when a score is offered as correctness / adequacy authority.

    Presence of a forbidden key is rejected unless the value is explicitly
    ``False`` or ``None`` (documentation that the score is *not* authority).
    Truthy values and numeric/string scores under forbidden keys fail closed.
    """

    stack: list[tuple[str, Any]] = [(path, value)]
    while stack:
        current_path, current = stack.pop()
        if isinstance(current, Mapping):
            for key, item in current.items():
                key_text = str(key)
                lowered = key_text.lower()
                if lowered in SCORE_AUTHORITY_FORBIDDEN_KEYS:
                    # Explicit False/None documents non-authority and is admitted.
                    if item is not False and item is not None:
                        raise AdequacyError(
                            f"{current_path}.{key_text} attempts to convert a "
                            f"score into correctness; scores never establish "
                            f"adequacy"
                        )
                if isinstance(item, (Mapping, list, tuple)):
                    stack.append((f"{current_path}.{key_text}", item))
        elif isinstance(current, (list, tuple)):
            for index, item in enumerate(current):
                if isinstance(item, (Mapping, list, tuple)):
                    stack.append((f"{current_path}[{index}]", item))


def _normalize_source_span(
    value: SourceSpan | Mapping[str, Any],
    name: str = "source_span",
) -> SourceSpan:
    if isinstance(value, SourceSpan):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "span_cid" in value:
            try:
                return SourceSpan.from_dict(value)
            except AnalysisContractError as exc:
                raise AdequacyError(str(exc)) from exc
        try:
            return SourceSpan(
                path=value["path"],
                start_line=value["start_line"],
                end_line=value["end_line"],
                start_col=value.get("start_col"),
                end_col=value.get("end_col"),
            )
        except (KeyError, AnalysisContractError, TypeError) as exc:
            raise AdequacyError(f"{name} is malformed: {exc}") from exc
    raise AdequacyError(f"{name} must be SourceSpan or mapping")


def _normalize_source_spans(
    values: Sequence[SourceSpan | Mapping[str, Any]],
    name: str = "source_spans",
) -> tuple[SourceSpan, ...]:
    if not isinstance(values, (list, tuple)):
        raise AdequacyError(f"{name} must be a list")
    if not values:
        raise AdequacyError(f"{name} must not be empty")
    if len(values) > MAX_SPANS:
        raise AdequacyError(f"{name} exceeds maximum length")
    spans = tuple(
        _normalize_source_span(item, f"{name}[{index}]")
        for index, item in enumerate(values)
    )
    return tuple(
        sorted(
            spans,
            key=lambda item: (item.path, item.start_line, item.end_line, item.span_cid),
        )
    )


def _normalize_evidence(
    value: MinimizedEvidenceBinding | Mapping[str, Any] | None,
    name: str = "minimized_evidence",
) -> MinimizedEvidenceBinding:
    if value is None:
        raise AdequacyError(f"{name} is required")
    if isinstance(value, MinimizedEvidenceBinding):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "binding_cid" in value:
                return MinimizedEvidenceBinding.from_dict(value)
            return MinimizedEvidenceBinding(
                evidence_cids=value["evidence_cids"],
                minimized=value.get("minimized", True),
                minimization_failed=value.get("minimization_failed", False),
                reproduction_input_cid=value.get("reproduction_input_cid"),
                notes=value.get("notes"),
            )
        except (KeyError, AnalysisContractError, TypeError) as exc:
            raise AdequacyError(f"{name} is malformed: {exc}") from exc
    raise AdequacyError(f"{name} must be MinimizedEvidenceBinding or mapping")


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except AssuranceBaseError as exc:
            raise AdequacyError(str(exc)) from exc
    raise AdequacyError(f"{name} must be AssuranceArtifactHeader or mapping")


def _profile_header(
    base: AssuranceArtifactHeader,
    *,
    artifact_kind: str,
    interface_id: str,
    symbol_ids: Sequence[str],
) -> AssuranceArtifactHeader:
    """Derive a profile header with generator pin for the adequacy builder."""

    generator = GeneratorIdentity(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=interface_id,
    )
    versions = VersionBinding(
        operator_id=base.versions.operator_id,
        operator_version=base.versions.operator_version,
        campaign_policy_id=base.versions.campaign_policy_id,
        campaign_policy_version=base.versions.campaign_policy_version,
        generator=generator,
    )
    return AssuranceArtifactHeader(
        artifact_kind=artifact_kind,
        repository_id=base.repository_id,
        repository_state_cid=base.repository_state_cid,
        target_symbol_ids=tuple(symbol_ids) if symbol_ids else tuple(base.target_symbol_ids),
        target_artifact_cids=tuple(base.target_artifact_cids),
        capsule_cids=tuple(base.capsule_cids),
        proof_unit_cids=tuple(base.proof_unit_cids),
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        versions=versions,
        provenance=base.provenance,
        terminal_status=base.terminal_status,
        receipt_cids=tuple(base.receipt_cids),
        proof_cids=tuple(base.proof_cids),
        metadata=dict(base.metadata),
    )


# ---------------------------------------------------------------------------
# Shared binding records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdequacyClaimBinding:
    """One claim bound into an adequacy profile subject.

    Interface payload schema: ``AdequacyClaimBinding@1`` (via schema constant).
    """

    claim_id: str
    claim_text: str
    property_class: str | None = None
    symbol_ids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "claim_id",
            "claim_text",
            "property_class",
            "symbol_ids",
            "notes",
            "metadata",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _token(self.claim_id, "claim_id"))
        object.__setattr__(self, "claim_text", _text(self.claim_text, "claim_text"))
        prop = self.property_class
        object.__setattr__(
            self,
            "property_class",
            _token(prop, "property_class") if prop is not None else None,
        )
        object.__setattr__(
            self,
            "symbol_ids",
            _unique_sorted_tokens(
                list(self.symbol_ids), "symbol_ids", symbol=True, maximum=MAX_LIST
            ),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ADEQUACY_CLAIM_BINDING_SCHEMA,
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "property_class": self.property_class,
            "symbol_ids": list(self.symbol_ids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["binding_cid"] = self.binding_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdequacyClaimBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != ADEQUACY_CLAIM_BINDING_SCHEMA:
            raise AdequacyError("unsupported AdequacyClaimBinding schema version")
        result = cls(
            claim_id=payload["claim_id"],
            claim_text=payload["claim_text"],
            property_class=payload["property_class"],
            symbol_ids=payload["symbol_ids"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.binding_cid:
            raise AdequacyError("AdequacyClaimBinding binding_cid identity mismatch")
        return result


@dataclass(frozen=True, slots=True)
class ReachableBehaviorBinding:
    """Reachable / exercised behavior bound into an adequacy subject."""

    behavior_id: str
    description: str
    reachable: bool = True
    exercised: bool = False
    required: bool = True
    symbol_ids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "behavior_id",
            "description",
            "reachable",
            "exercised",
            "required",
            "symbol_ids",
            "notes",
            "metadata",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "behavior_id", _token(self.behavior_id, "behavior_id"))
        object.__setattr__(
            self, "description", _text(self.description, "description")
        )
        reachable = _bool(self.reachable, "reachable")
        exercised = _bool(self.exercised, "exercised")
        if exercised and not reachable:
            raise AdequacyError(
                "exercised behavior must also be marked reachable"
            )
        object.__setattr__(self, "reachable", reachable)
        object.__setattr__(self, "exercised", exercised)
        object.__setattr__(self, "required", _bool(self.required, "required"))
        object.__setattr__(
            self,
            "symbol_ids",
            _unique_sorted_tokens(
                list(self.symbol_ids), "symbol_ids", symbol=True, maximum=MAX_LIST
            ),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": REACHABLE_BEHAVIOR_BINDING_SCHEMA,
            "behavior_id": self.behavior_id,
            "description": self.description,
            "reachable": self.reachable,
            "exercised": self.exercised,
            "required": self.required,
            "symbol_ids": list(self.symbol_ids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["binding_cid"] = self.binding_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReachableBehaviorBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != REACHABLE_BEHAVIOR_BINDING_SCHEMA:
            raise AdequacyError(
                "unsupported ReachableBehaviorBinding schema version"
            )
        result = cls(
            behavior_id=payload["behavior_id"],
            description=payload["description"],
            reachable=payload["reachable"],
            exercised=payload["exercised"],
            required=payload["required"],
            symbol_ids=payload["symbol_ids"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.binding_cid:
            raise AdequacyError(
                "ReachableBehaviorBinding binding_cid identity mismatch"
            )
        return result


@dataclass(frozen=True, slots=True)
class DetectorAdequacyBinding:
    """Detector role bound into an adequacy subject."""

    detector_id: str
    role: DetectorAdequacyRole | str
    detector_kind: str | None = None
    claim_ids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "detector_id",
            "role",
            "detector_kind",
            "claim_ids",
            "notes",
            "metadata",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "detector_id", _token(self.detector_id, "detector_id")
        )
        object.__setattr__(
            self, "role", _enum(self.role, DetectorAdequacyRole, "role")
        )
        kind = self.detector_kind
        object.__setattr__(
            self,
            "detector_kind",
            _token(kind, "detector_kind") if kind is not None else None,
        )
        object.__setattr__(
            self,
            "claim_ids",
            _unique_sorted_tokens(list(self.claim_ids), "claim_ids", maximum=MAX_CLAIMS),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DETECTOR_ADEQUACY_BINDING_SCHEMA,
            "detector_id": self.detector_id,
            "role": self.role,
            "detector_kind": self.detector_kind,
            "claim_ids": list(self.claim_ids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["binding_cid"] = self.binding_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DetectorAdequacyBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != DETECTOR_ADEQUACY_BINDING_SCHEMA:
            raise AdequacyError(
                "unsupported DetectorAdequacyBinding schema version"
            )
        result = cls(
            detector_id=payload["detector_id"],
            role=payload["role"],
            detector_kind=payload["detector_kind"],
            claim_ids=payload["claim_ids"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.binding_cid:
            raise AdequacyError(
                "DetectorAdequacyBinding binding_cid identity mismatch"
            )
        return result


@dataclass(frozen=True, slots=True)
class FalseAssuranceEvidenceBinding:
    """Evidence that current assurance accepted an incorrect behavior."""

    evidence_id: str
    evidence_kind: FalseAssuranceEvidenceKind | str
    evidence_cid: str
    summary: str
    claim_ids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "evidence_id",
            "evidence_kind",
            "evidence_cid",
            "summary",
            "claim_ids",
            "notes",
            "metadata",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _token(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self,
            "evidence_kind",
            _enum(self.evidence_kind, FalseAssuranceEvidenceKind, "evidence_kind"),
        )
        object.__setattr__(
            self, "evidence_cid", _cid(self.evidence_cid, "evidence_cid")
        )
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        object.__setattr__(
            self,
            "claim_ids",
            _unique_sorted_tokens(list(self.claim_ids), "claim_ids", maximum=MAX_CLAIMS),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": FALSE_ASSURANCE_EVIDENCE_SCHEMA,
            "evidence_id": self.evidence_id,
            "evidence_kind": self.evidence_kind,
            "evidence_cid": self.evidence_cid,
            "summary": self.summary,
            "claim_ids": list(self.claim_ids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["binding_cid"] = self.binding_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FalseAssuranceEvidenceBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != FALSE_ASSURANCE_EVIDENCE_SCHEMA:
            raise AdequacyError(
                "unsupported FalseAssuranceEvidenceBinding schema version"
            )
        result = cls(
            evidence_id=payload["evidence_id"],
            evidence_kind=payload["evidence_kind"],
            evidence_cid=payload["evidence_cid"],
            summary=payload["summary"],
            claim_ids=payload["claim_ids"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.binding_cid:
            raise AdequacyError(
                "FalseAssuranceEvidenceBinding binding_cid identity mismatch"
            )
        return result


@dataclass(frozen=True, slots=True)
class UncertaintyBinding:
    """Uncertainty that qualifies or blocks an adequacy verdict."""

    uncertainty_id: str
    kind: UncertaintyKind | str
    description: str
    blocks_adequacy: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "uncertainty_id",
            "kind",
            "description",
            "blocks_adequacy",
            "notes",
            "metadata",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "uncertainty_id", _token(self.uncertainty_id, "uncertainty_id")
        )
        object.__setattr__(self, "kind", _enum(self.kind, UncertaintyKind, "kind"))
        object.__setattr__(
            self, "description", _text(self.description, "description")
        )
        object.__setattr__(
            self,
            "blocks_adequacy",
            _bool(self.blocks_adequacy, "blocks_adequacy"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": UNCERTAINTY_BINDING_SCHEMA,
            "uncertainty_id": self.uncertainty_id,
            "kind": self.kind,
            "description": self.description,
            "blocks_adequacy": self.blocks_adequacy,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["binding_cid"] = self.binding_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UncertaintyBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != UNCERTAINTY_BINDING_SCHEMA:
            raise AdequacyError("unsupported UncertaintyBinding schema version")
        result = cls(
            uncertainty_id=payload["uncertainty_id"],
            kind=payload["kind"],
            description=payload["description"],
            blocks_adequacy=payload["blocks_adequacy"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.binding_cid:
            raise AdequacyError("UncertaintyBinding binding_cid identity mismatch")
        return result


@dataclass(frozen=True, slots=True)
class AdequacyScopeBinding:
    """Explicit in-scope / out-of-scope bounds for an adequacy profile."""

    scope_id: str
    target_symbol_ids: Sequence[str]
    in_scope_artifact_cids: Sequence[str] = ()
    out_of_scope_symbol_ids: Sequence[str] = ()
    out_of_scope_notes: Sequence[str] = ()
    repository_state_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "scope_id",
            "target_symbol_ids",
            "in_scope_artifact_cids",
            "out_of_scope_symbol_ids",
            "out_of_scope_notes",
            "repository_state_cid",
            "notes",
            "metadata",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", _token(self.scope_id, "scope_id"))
        targets = _unique_sorted_tokens(
            list(self.target_symbol_ids),
            "target_symbol_ids",
            symbol=True,
            maximum=MAX_LIST,
        )
        if not targets:
            raise AdequacyError("target_symbol_ids must not be empty")
        object.__setattr__(self, "target_symbol_ids", targets)
        object.__setattr__(
            self,
            "in_scope_artifact_cids",
            _unique_sorted_cids(
                list(self.in_scope_artifact_cids),
                "in_scope_artifact_cids",
                maximum=MAX_LIST,
            ),
        )
        out_symbols = _unique_sorted_tokens(
            list(self.out_of_scope_symbol_ids),
            "out_of_scope_symbol_ids",
            symbol=True,
            maximum=MAX_LIST,
        )
        overlap = sorted(set(targets) & set(out_symbols))
        if overlap:
            raise AdequacyError(
                "target_symbol_ids and out_of_scope_symbol_ids must be disjoint; "
                f"overlap={overlap}"
            )
        object.__setattr__(self, "out_of_scope_symbol_ids", out_symbols)
        object.__setattr__(
            self,
            "out_of_scope_notes",
            _unique_sorted_texts(
                list(self.out_of_scope_notes),
                "out_of_scope_notes",
                maximum=MAX_LIST,
            ),
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _optional_cid(self.repository_state_cid, "repository_state_cid"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ADEQUACY_SCOPE_BINDING_SCHEMA,
            "scope_id": self.scope_id,
            "target_symbol_ids": list(self.target_symbol_ids),
            "in_scope_artifact_cids": list(self.in_scope_artifact_cids),
            "out_of_scope_symbol_ids": list(self.out_of_scope_symbol_ids),
            "out_of_scope_notes": list(self.out_of_scope_notes),
            "repository_state_cid": self.repository_state_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["binding_cid"] = self.binding_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdequacyScopeBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != ADEQUACY_SCOPE_BINDING_SCHEMA:
            raise AdequacyError("unsupported AdequacyScopeBinding schema version")
        result = cls(
            scope_id=payload["scope_id"],
            target_symbol_ids=payload["target_symbol_ids"],
            in_scope_artifact_cids=payload["in_scope_artifact_cids"],
            out_of_scope_symbol_ids=payload["out_of_scope_symbol_ids"],
            out_of_scope_notes=payload["out_of_scope_notes"],
            repository_state_cid=payload["repository_state_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.binding_cid:
            raise AdequacyError("AdequacyScopeBinding binding_cid identity mismatch")
        return result


# ---------------------------------------------------------------------------
# List normalizers for binding collections
# ---------------------------------------------------------------------------


def _normalize_claims(
    values: Sequence[AdequacyClaimBinding | Mapping[str, Any]],
    name: str = "claims",
) -> tuple[AdequacyClaimBinding, ...]:
    if not isinstance(values, (list, tuple)):
        raise AdequacyError(f"{name} must be a list")
    if not values:
        raise AdequacyError(f"{name} must not be empty")
    if len(values) > MAX_CLAIMS:
        raise AdequacyError(f"{name} exceeds maximum length")
    items: list[AdequacyClaimBinding] = []
    for index, raw in enumerate(values):
        if isinstance(raw, AdequacyClaimBinding):
            items.append(raw)
        elif isinstance(raw, Mapping):
            if "schema" in raw or "binding_cid" in raw:
                items.append(AdequacyClaimBinding.from_dict(raw))
            else:
                items.append(
                    AdequacyClaimBinding(
                        claim_id=raw["claim_id"],
                        claim_text=raw["claim_text"],
                        property_class=raw.get("property_class"),
                        symbol_ids=raw.get("symbol_ids", ()),
                        notes=raw.get("notes"),
                        metadata=raw.get("metadata", {}),
                    )
                )
        else:
            raise AdequacyError(f"{name}[{index}] must be AdequacyClaimBinding or mapping")
    ids = [item.claim_id for item in items]
    if len(ids) != len(set(ids)):
        raise AdequacyError(f"{name} claim_id values must be unique")
    return tuple(sorted(items, key=lambda item: item.claim_id))


def _normalize_behaviors(
    values: Sequence[ReachableBehaviorBinding | Mapping[str, Any]],
    name: str = "reachable_behaviors",
) -> tuple[ReachableBehaviorBinding, ...]:
    if not isinstance(values, (list, tuple)):
        raise AdequacyError(f"{name} must be a list")
    if not values:
        raise AdequacyError(f"{name} must not be empty")
    if len(values) > MAX_BEHAVIORS:
        raise AdequacyError(f"{name} exceeds maximum length")
    items: list[ReachableBehaviorBinding] = []
    for index, raw in enumerate(values):
        if isinstance(raw, ReachableBehaviorBinding):
            items.append(raw)
        elif isinstance(raw, Mapping):
            if "schema" in raw or "binding_cid" in raw:
                items.append(ReachableBehaviorBinding.from_dict(raw))
            else:
                items.append(
                    ReachableBehaviorBinding(
                        behavior_id=raw["behavior_id"],
                        description=raw["description"],
                        reachable=raw.get("reachable", True),
                        exercised=raw.get("exercised", False),
                        required=raw.get("required", True),
                        symbol_ids=raw.get("symbol_ids", ()),
                        notes=raw.get("notes"),
                        metadata=raw.get("metadata", {}),
                    )
                )
        else:
            raise AdequacyError(
                f"{name}[{index}] must be ReachableBehaviorBinding or mapping"
            )
    ids = [item.behavior_id for item in items]
    if len(ids) != len(set(ids)):
        raise AdequacyError(f"{name} behavior_id values must be unique")
    return tuple(sorted(items, key=lambda item: item.behavior_id))


def _normalize_detectors(
    values: Sequence[DetectorAdequacyBinding | Mapping[str, Any]],
    name: str = "detectors",
) -> tuple[DetectorAdequacyBinding, ...]:
    if not isinstance(values, (list, tuple)):
        raise AdequacyError(f"{name} must be a list")
    if len(values) > MAX_DETECTORS:
        raise AdequacyError(f"{name} exceeds maximum length")
    items: list[DetectorAdequacyBinding] = []
    for index, raw in enumerate(values):
        if isinstance(raw, DetectorAdequacyBinding):
            items.append(raw)
        elif isinstance(raw, Mapping):
            if "schema" in raw or "binding_cid" in raw:
                items.append(DetectorAdequacyBinding.from_dict(raw))
            else:
                items.append(
                    DetectorAdequacyBinding(
                        detector_id=raw["detector_id"],
                        role=raw["role"],
                        detector_kind=raw.get("detector_kind"),
                        claim_ids=raw.get("claim_ids", ()),
                        notes=raw.get("notes"),
                        metadata=raw.get("metadata", {}),
                    )
                )
        else:
            raise AdequacyError(
                f"{name}[{index}] must be DetectorAdequacyBinding or mapping"
            )
    ids = [item.detector_id for item in items]
    if len(ids) != len(set(ids)):
        raise AdequacyError(f"{name} detector_id values must be unique")
    covered = {item.detector_id for item in items if item.role == DetectorAdequacyRole.COVERED.value}
    missing = {item.detector_id for item in items if item.role == DetectorAdequacyRole.MISSING.value}
    overlap = sorted(covered & missing)
    if overlap:
        raise AdequacyError(
            f"{name} covered and missing detector roles must be disjoint; "
            f"overlap={overlap}"
        )
    return tuple(sorted(items, key=lambda item: item.detector_id))


def _normalize_false_assurance(
    values: Sequence[FalseAssuranceEvidenceBinding | Mapping[str, Any]],
    name: str = "false_assurance_evidence",
) -> tuple[FalseAssuranceEvidenceBinding, ...]:
    if not isinstance(values, (list, tuple)):
        raise AdequacyError(f"{name} must be a list")
    if len(values) > MAX_EVIDENCE:
        raise AdequacyError(f"{name} exceeds maximum length")
    items: list[FalseAssuranceEvidenceBinding] = []
    for index, raw in enumerate(values):
        if isinstance(raw, FalseAssuranceEvidenceBinding):
            items.append(raw)
        elif isinstance(raw, Mapping):
            if "schema" in raw or "binding_cid" in raw:
                items.append(FalseAssuranceEvidenceBinding.from_dict(raw))
            else:
                items.append(
                    FalseAssuranceEvidenceBinding(
                        evidence_id=raw["evidence_id"],
                        evidence_kind=raw["evidence_kind"],
                        evidence_cid=raw["evidence_cid"],
                        summary=raw["summary"],
                        claim_ids=raw.get("claim_ids", ()),
                        notes=raw.get("notes"),
                        metadata=raw.get("metadata", {}),
                    )
                )
        else:
            raise AdequacyError(
                f"{name}[{index}] must be FalseAssuranceEvidenceBinding or mapping"
            )
    ids = [item.evidence_id for item in items]
    if len(ids) != len(set(ids)):
        raise AdequacyError(f"{name} evidence_id values must be unique")
    return tuple(sorted(items, key=lambda item: item.evidence_id))


def _normalize_uncertainty(
    values: Sequence[UncertaintyBinding | Mapping[str, Any]],
    name: str = "uncertainty",
) -> tuple[UncertaintyBinding, ...]:
    if not isinstance(values, (list, tuple)):
        raise AdequacyError(f"{name} must be a list")
    if len(values) > MAX_UNCERTAINTY:
        raise AdequacyError(f"{name} exceeds maximum length")
    items: list[UncertaintyBinding] = []
    for index, raw in enumerate(values):
        if isinstance(raw, UncertaintyBinding):
            items.append(raw)
        elif isinstance(raw, Mapping):
            if "schema" in raw or "binding_cid" in raw:
                items.append(UncertaintyBinding.from_dict(raw))
            else:
                items.append(
                    UncertaintyBinding(
                        uncertainty_id=raw["uncertainty_id"],
                        kind=raw["kind"],
                        description=raw["description"],
                        blocks_adequacy=raw.get("blocks_adequacy", True),
                        notes=raw.get("notes"),
                        metadata=raw.get("metadata", {}),
                    )
                )
        else:
            raise AdequacyError(
                f"{name}[{index}] must be UncertaintyBinding or mapping"
            )
    ids = [item.uncertainty_id for item in items]
    if len(ids) != len(set(ids)):
        raise AdequacyError(f"{name} uncertainty_id values must be unique")
    return tuple(sorted(items, key=lambda item: item.uncertainty_id))


def _normalize_scope(
    value: AdequacyScopeBinding | Mapping[str, Any],
    name: str = "scope",
) -> AdequacyScopeBinding:
    if isinstance(value, AdequacyScopeBinding):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "binding_cid" in value:
            return AdequacyScopeBinding.from_dict(value)
        return AdequacyScopeBinding(
            scope_id=value["scope_id"],
            target_symbol_ids=value["target_symbol_ids"],
            in_scope_artifact_cids=value.get("in_scope_artifact_cids", ()),
            out_of_scope_symbol_ids=value.get("out_of_scope_symbol_ids", ()),
            out_of_scope_notes=value.get("out_of_scope_notes", ()),
            repository_state_cid=value.get("repository_state_cid"),
            notes=value.get("notes"),
            metadata=value.get("metadata", {}),
        )
    raise AdequacyError(f"{name} must be AdequacyScopeBinding or mapping")


def _normalize_gap_signals(
    values: Sequence[Any],
    enum_type: type[Enum],
    name: str,
) -> tuple[str, ...]:
    """Normalize optional explicit gap-class signals (excluding exclusive none)."""

    if not isinstance(values, (list, tuple)):
        raise AdequacyError(f"{name} must be a list")
    if len(values) > MAX_GAPS:
        raise AdequacyError(f"{name} exceeds maximum length")
    if not values:
        return ()
    seen: set[str] = set()
    out: list[str] = []
    for index, raw in enumerate(values):
        item = _enum(raw, enum_type, f"{name}[{index}]")
        if item == "none":
            raise AdequacyError(
                f"{name} must not include 'none'; the builder emits 'none' "
                f"only when no gaps remain"
            )
        if item in seen:
            raise AdequacyError(f"{name} must not contain duplicates")
        seen.add(item)
        out.append(item)
    return tuple(sorted(out))


# ---------------------------------------------------------------------------
# Surface subjects
# ---------------------------------------------------------------------------


def _common_subject_fields() -> frozenset[str]:
    return frozenset(
        {
            "schema",
            "subject_id",
            "profile_id",
            "claims",
            "reachable_behaviors",
            "detectors",
            "false_assurance_evidence",
            "uncertainty",
            "scope",
            "gap_signals",
            "source_spans",
            "minimized_evidence",
            "observation_complete",
            "notes",
            "metadata",
            "subject_observation_cid",
        }
    )


@dataclass(frozen=True, slots=True)
class TestAdequacySubject:
    """Sealed observation subject for test-surface adequacy construction."""

    subject_id: str
    profile_id: str
    claims: Sequence[AdequacyClaimBinding | Mapping[str, Any]]
    reachable_behaviors: Sequence[ReachableBehaviorBinding | Mapping[str, Any]]
    detectors: Sequence[DetectorAdequacyBinding | Mapping[str, Any]]
    scope: AdequacyScopeBinding | Mapping[str, Any]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    false_assurance_evidence: Sequence[
        FalseAssuranceEvidenceBinding | Mapping[str, Any]
    ] = ()
    uncertainty: Sequence[UncertaintyBinding | Mapping[str, Any]] = ()
    gap_signals: Sequence[TestAdequacyGapClass | str] = ()
    # Explicit test-surface signal flags (deterministic gap derivation).
    weak_assertions: bool = False
    tautology_assertions: bool = False
    uncalled_targets: bool = False
    permanent_skips: bool = False
    mock_bypasses: bool = False
    fixture_bypasses: bool = False
    success_before_effect: bool = False
    type_only_coverage: bool = False
    selection_misses: bool = False
    observation_complete: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = _common_subject_fields() | frozenset(
        {
            "weak_assertions",
            "tautology_assertions",
            "uncalled_targets",
            "permanent_skips",
            "mock_bypasses",
            "fixture_bypasses",
            "success_before_effect",
            "type_only_coverage",
            "selection_misses",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(self, "profile_id", _token(self.profile_id, "profile_id"))
        object.__setattr__(self, "claims", _normalize_claims(list(self.claims)))
        object.__setattr__(
            self,
            "reachable_behaviors",
            _normalize_behaviors(list(self.reachable_behaviors)),
        )
        object.__setattr__(
            self, "detectors", _normalize_detectors(list(self.detectors))
        )
        object.__setattr__(
            self,
            "false_assurance_evidence",
            _normalize_false_assurance(list(self.false_assurance_evidence)),
        )
        object.__setattr__(
            self, "uncertainty", _normalize_uncertainty(list(self.uncertainty))
        )
        object.__setattr__(self, "scope", _normalize_scope(self.scope))
        object.__setattr__(
            self,
            "gap_signals",
            _normalize_gap_signals(
                list(self.gap_signals), TestAdequacyGapClass, "gap_signals"
            ),
        )
        object.__setattr__(
            self, "source_spans", _normalize_source_spans(list(self.source_spans))
        )
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_evidence(self.minimized_evidence),
        )
        for flag in (
            "weak_assertions",
            "tautology_assertions",
            "uncalled_targets",
            "permanent_skips",
            "mock_bypasses",
            "fixture_bypasses",
            "success_before_effect",
            "type_only_coverage",
            "selection_misses",
            "observation_complete",
        ):
            object.__setattr__(self, flag, _bool(getattr(self, flag), flag))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TEST_ADEQUACY_SUBJECT_SCHEMA,
            "subject_id": self.subject_id,
            "profile_id": self.profile_id,
            "claims": [item.identity_payload() for item in self.claims],
            "reachable_behaviors": [
                item.identity_payload() for item in self.reachable_behaviors
            ],
            "detectors": [item.identity_payload() for item in self.detectors],
            "false_assurance_evidence": [
                item.identity_payload() for item in self.false_assurance_evidence
            ],
            "uncertainty": [item.identity_payload() for item in self.uncertainty],
            "scope": self.scope.identity_payload(),
            "gap_signals": list(self.gap_signals),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "weak_assertions": self.weak_assertions,
            "tautology_assertions": self.tautology_assertions,
            "uncalled_targets": self.uncalled_targets,
            "permanent_skips": self.permanent_skips,
            "mock_bypasses": self.mock_bypasses,
            "fixture_bypasses": self.fixture_bypasses,
            "success_before_effect": self.success_before_effect,
            "type_only_coverage": self.type_only_coverage,
            "selection_misses": self.selection_misses,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def subject_observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["claims"] = [item.to_dict() for item in self.claims]
        value["reachable_behaviors"] = [
            item.to_dict() for item in self.reachable_behaviors
        ]
        value["detectors"] = [item.to_dict() for item in self.detectors]
        value["false_assurance_evidence"] = [
            item.to_dict() for item in self.false_assurance_evidence
        ]
        value["uncertainty"] = [item.to_dict() for item in self.uncertainty]
        value["scope"] = self.scope.to_dict()
        value["source_spans"] = [span.to_dict() for span in self.source_spans]
        value["minimized_evidence"] = self.minimized_evidence.to_dict()
        value["subject_observation_cid"] = self.subject_observation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestAdequacySubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("subject_observation_cid")
        if payload.pop("schema") != TEST_ADEQUACY_SUBJECT_SCHEMA:
            raise AdequacyError("unsupported TestAdequacySubject schema version")
        result = cls(**payload)  # type: ignore[arg-type]
        if claimed != result.subject_observation_cid:
            raise AdequacyError(
                "TestAdequacySubject subject_observation_cid identity mismatch"
            )
        return result


@dataclass(frozen=True, slots=True)
class ProofAdequacySubject:
    """Sealed observation subject for proof-surface adequacy construction."""

    subject_id: str
    profile_id: str
    claims: Sequence[AdequacyClaimBinding | Mapping[str, Any]]
    reachable_behaviors: Sequence[ReachableBehaviorBinding | Mapping[str, Any]]
    detectors: Sequence[DetectorAdequacyBinding | Mapping[str, Any]]
    scope: AdequacyScopeBinding | Mapping[str, Any]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    proof_unit_cids: Sequence[str] = ()
    missing_obligation_ids: Sequence[str] = ()
    false_assurance_evidence: Sequence[
        FalseAssuranceEvidenceBinding | Mapping[str, Any]
    ] = ()
    uncertainty: Sequence[UncertaintyBinding | Mapping[str, Any]] = ()
    gap_signals: Sequence[ProofAdequacyGapClass | str] = ()
    vacuous_proof: bool = False
    unsatisfiable_antecedent: bool = False
    unreachable_state: bool = False
    assumed_not_proven: bool = False
    omitted_behavior: bool = False
    stale_proof_unit: bool = False
    observation_complete: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = _common_subject_fields() | frozenset(
        {
            "proof_unit_cids",
            "missing_obligation_ids",
            "vacuous_proof",
            "unsatisfiable_antecedent",
            "unreachable_state",
            "assumed_not_proven",
            "omitted_behavior",
            "stale_proof_unit",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(self, "profile_id", _token(self.profile_id, "profile_id"))
        object.__setattr__(self, "claims", _normalize_claims(list(self.claims)))
        object.__setattr__(
            self,
            "reachable_behaviors",
            _normalize_behaviors(list(self.reachable_behaviors)),
        )
        object.__setattr__(
            self, "detectors", _normalize_detectors(list(self.detectors))
        )
        object.__setattr__(
            self,
            "false_assurance_evidence",
            _normalize_false_assurance(list(self.false_assurance_evidence)),
        )
        object.__setattr__(
            self, "uncertainty", _normalize_uncertainty(list(self.uncertainty))
        )
        object.__setattr__(self, "scope", _normalize_scope(self.scope))
        object.__setattr__(
            self,
            "gap_signals",
            _normalize_gap_signals(
                list(self.gap_signals), ProofAdequacyGapClass, "gap_signals"
            ),
        )
        object.__setattr__(
            self, "source_spans", _normalize_source_spans(list(self.source_spans))
        )
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_evidence(self.minimized_evidence),
        )
        object.__setattr__(
            self,
            "proof_unit_cids",
            _unique_sorted_cids(list(self.proof_unit_cids), "proof_unit_cids"),
        )
        object.__setattr__(
            self,
            "missing_obligation_ids",
            _unique_sorted_tokens(
                list(self.missing_obligation_ids),
                "missing_obligation_ids",
                maximum=MAX_LIST,
            ),
        )
        for flag in (
            "vacuous_proof",
            "unsatisfiable_antecedent",
            "unreachable_state",
            "assumed_not_proven",
            "omitted_behavior",
            "stale_proof_unit",
            "observation_complete",
        ):
            object.__setattr__(self, flag, _bool(getattr(self, flag), flag))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PROOF_ADEQUACY_SUBJECT_SCHEMA,
            "subject_id": self.subject_id,
            "profile_id": self.profile_id,
            "claims": [item.identity_payload() for item in self.claims],
            "reachable_behaviors": [
                item.identity_payload() for item in self.reachable_behaviors
            ],
            "detectors": [item.identity_payload() for item in self.detectors],
            "false_assurance_evidence": [
                item.identity_payload() for item in self.false_assurance_evidence
            ],
            "uncertainty": [item.identity_payload() for item in self.uncertainty],
            "scope": self.scope.identity_payload(),
            "gap_signals": list(self.gap_signals),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "proof_unit_cids": list(self.proof_unit_cids),
            "missing_obligation_ids": list(self.missing_obligation_ids),
            "vacuous_proof": self.vacuous_proof,
            "unsatisfiable_antecedent": self.unsatisfiable_antecedent,
            "unreachable_state": self.unreachable_state,
            "assumed_not_proven": self.assumed_not_proven,
            "omitted_behavior": self.omitted_behavior,
            "stale_proof_unit": self.stale_proof_unit,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def subject_observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["claims"] = [item.to_dict() for item in self.claims]
        value["reachable_behaviors"] = [
            item.to_dict() for item in self.reachable_behaviors
        ]
        value["detectors"] = [item.to_dict() for item in self.detectors]
        value["false_assurance_evidence"] = [
            item.to_dict() for item in self.false_assurance_evidence
        ]
        value["uncertainty"] = [item.to_dict() for item in self.uncertainty]
        value["scope"] = self.scope.to_dict()
        value["source_spans"] = [span.to_dict() for span in self.source_spans]
        value["minimized_evidence"] = self.minimized_evidence.to_dict()
        value["subject_observation_cid"] = self.subject_observation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProofAdequacySubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("subject_observation_cid")
        if payload.pop("schema") != PROOF_ADEQUACY_SUBJECT_SCHEMA:
            raise AdequacyError("unsupported ProofAdequacySubject schema version")
        result = cls(**payload)  # type: ignore[arg-type]
        if claimed != result.subject_observation_cid:
            raise AdequacyError(
                "ProofAdequacySubject subject_observation_cid identity mismatch"
            )
        return result


@dataclass(frozen=True, slots=True)
class PolicyAdequacySubject:
    """Sealed observation subject for policy-surface adequacy construction."""

    subject_id: str
    profile_id: str
    claims: Sequence[AdequacyClaimBinding | Mapping[str, Any]]
    reachable_behaviors: Sequence[ReachableBehaviorBinding | Mapping[str, Any]]
    detectors: Sequence[DetectorAdequacyBinding | Mapping[str, Any]]
    scope: AdequacyScopeBinding | Mapping[str, Any]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    policy_cids: Sequence[str] = ()
    missing_constraint_ids: Sequence[str] = ()
    false_assurance_evidence: Sequence[
        FalseAssuranceEvidenceBinding | Mapping[str, Any]
    ] = ()
    uncertainty: Sequence[UncertaintyBinding | Mapping[str, Any]] = ()
    gap_signals: Sequence[PolicyAdequacyGapClass | str] = ()
    unreachable_rule: bool = False
    shadowed_prohibition: bool = False
    dominating_default: bool = False
    impossible_obligation: bool = False
    obsolete_interface: bool = False
    stale_policy: bool = False
    observation_complete: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = _common_subject_fields() | frozenset(
        {
            "policy_cids",
            "missing_constraint_ids",
            "unreachable_rule",
            "shadowed_prohibition",
            "dominating_default",
            "impossible_obligation",
            "obsolete_interface",
            "stale_policy",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(self, "profile_id", _token(self.profile_id, "profile_id"))
        object.__setattr__(self, "claims", _normalize_claims(list(self.claims)))
        object.__setattr__(
            self,
            "reachable_behaviors",
            _normalize_behaviors(list(self.reachable_behaviors)),
        )
        object.__setattr__(
            self, "detectors", _normalize_detectors(list(self.detectors))
        )
        object.__setattr__(
            self,
            "false_assurance_evidence",
            _normalize_false_assurance(list(self.false_assurance_evidence)),
        )
        object.__setattr__(
            self, "uncertainty", _normalize_uncertainty(list(self.uncertainty))
        )
        object.__setattr__(self, "scope", _normalize_scope(self.scope))
        object.__setattr__(
            self,
            "gap_signals",
            _normalize_gap_signals(
                list(self.gap_signals), PolicyAdequacyGapClass, "gap_signals"
            ),
        )
        object.__setattr__(
            self, "source_spans", _normalize_source_spans(list(self.source_spans))
        )
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_evidence(self.minimized_evidence),
        )
        object.__setattr__(
            self,
            "policy_cids",
            _unique_sorted_cids(list(self.policy_cids), "policy_cids"),
        )
        object.__setattr__(
            self,
            "missing_constraint_ids",
            _unique_sorted_tokens(
                list(self.missing_constraint_ids),
                "missing_constraint_ids",
                maximum=MAX_LIST,
            ),
        )
        for flag in (
            "unreachable_rule",
            "shadowed_prohibition",
            "dominating_default",
            "impossible_obligation",
            "obsolete_interface",
            "stale_policy",
            "observation_complete",
        ):
            object.__setattr__(self, flag, _bool(getattr(self, flag), flag))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": POLICY_ADEQUACY_SUBJECT_SCHEMA,
            "subject_id": self.subject_id,
            "profile_id": self.profile_id,
            "claims": [item.identity_payload() for item in self.claims],
            "reachable_behaviors": [
                item.identity_payload() for item in self.reachable_behaviors
            ],
            "detectors": [item.identity_payload() for item in self.detectors],
            "false_assurance_evidence": [
                item.identity_payload() for item in self.false_assurance_evidence
            ],
            "uncertainty": [item.identity_payload() for item in self.uncertainty],
            "scope": self.scope.identity_payload(),
            "gap_signals": list(self.gap_signals),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "policy_cids": list(self.policy_cids),
            "missing_constraint_ids": list(self.missing_constraint_ids),
            "unreachable_rule": self.unreachable_rule,
            "shadowed_prohibition": self.shadowed_prohibition,
            "dominating_default": self.dominating_default,
            "impossible_obligation": self.impossible_obligation,
            "obsolete_interface": self.obsolete_interface,
            "stale_policy": self.stale_policy,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def subject_observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["claims"] = [item.to_dict() for item in self.claims]
        value["reachable_behaviors"] = [
            item.to_dict() for item in self.reachable_behaviors
        ]
        value["detectors"] = [item.to_dict() for item in self.detectors]
        value["false_assurance_evidence"] = [
            item.to_dict() for item in self.false_assurance_evidence
        ]
        value["uncertainty"] = [item.to_dict() for item in self.uncertainty]
        value["scope"] = self.scope.to_dict()
        value["source_spans"] = [span.to_dict() for span in self.source_spans]
        value["minimized_evidence"] = self.minimized_evidence.to_dict()
        value["subject_observation_cid"] = self.subject_observation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PolicyAdequacySubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("subject_observation_cid")
        if payload.pop("schema") != POLICY_ADEQUACY_SUBJECT_SCHEMA:
            raise AdequacyError("unsupported PolicyAdequacySubject schema version")
        result = cls(**payload)  # type: ignore[arg-type]
        if claimed != result.subject_observation_cid:
            raise AdequacyError(
                "PolicyAdequacySubject subject_observation_cid identity mismatch"
            )
        return result


@dataclass(frozen=True, slots=True)
class CapsuleAdequacySubject:
    """Sealed observation subject for capsule-surface adequacy construction."""

    subject_id: str
    profile_id: str
    claims: Sequence[AdequacyClaimBinding | Mapping[str, Any]]
    reachable_behaviors: Sequence[ReachableBehaviorBinding | Mapping[str, Any]]
    detectors: Sequence[DetectorAdequacyBinding | Mapping[str, Any]]
    scope: AdequacyScopeBinding | Mapping[str, Any]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    capsule_cids: Sequence[str] = ()
    omitted_edge_ids: Sequence[str] = ()
    false_assurance_evidence: Sequence[
        FalseAssuranceEvidenceBinding | Mapping[str, Any]
    ] = ()
    uncertainty: Sequence[UncertaintyBinding | Mapping[str, Any]] = ()
    gap_signals: Sequence[CapsuleAdequacyGapClass | str] = ()
    omitted_dependency: bool = False
    omitted_config: bool = False
    omitted_fixture: bool = False
    omitted_exception: bool = False
    omitted_effect: bool = False
    stale_capsule: bool = False
    wrong_root: bool = False
    heuristic_as_exact: bool = False
    opaque_as_exact: bool = False
    selection_miss: bool = False
    observation_complete: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = _common_subject_fields() | frozenset(
        {
            "capsule_cids",
            "omitted_edge_ids",
            "omitted_dependency",
            "omitted_config",
            "omitted_fixture",
            "omitted_exception",
            "omitted_effect",
            "stale_capsule",
            "wrong_root",
            "heuristic_as_exact",
            "opaque_as_exact",
            "selection_miss",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(self, "profile_id", _token(self.profile_id, "profile_id"))
        object.__setattr__(self, "claims", _normalize_claims(list(self.claims)))
        object.__setattr__(
            self,
            "reachable_behaviors",
            _normalize_behaviors(list(self.reachable_behaviors)),
        )
        object.__setattr__(
            self, "detectors", _normalize_detectors(list(self.detectors))
        )
        object.__setattr__(
            self,
            "false_assurance_evidence",
            _normalize_false_assurance(list(self.false_assurance_evidence)),
        )
        object.__setattr__(
            self, "uncertainty", _normalize_uncertainty(list(self.uncertainty))
        )
        object.__setattr__(self, "scope", _normalize_scope(self.scope))
        object.__setattr__(
            self,
            "gap_signals",
            _normalize_gap_signals(
                list(self.gap_signals), CapsuleAdequacyGapClass, "gap_signals"
            ),
        )
        object.__setattr__(
            self, "source_spans", _normalize_source_spans(list(self.source_spans))
        )
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_evidence(self.minimized_evidence),
        )
        object.__setattr__(
            self,
            "capsule_cids",
            _unique_sorted_cids(list(self.capsule_cids), "capsule_cids"),
        )
        object.__setattr__(
            self,
            "omitted_edge_ids",
            _unique_sorted_tokens(
                list(self.omitted_edge_ids),
                "omitted_edge_ids",
                maximum=MAX_LIST,
            ),
        )
        for flag in (
            "omitted_dependency",
            "omitted_config",
            "omitted_fixture",
            "omitted_exception",
            "omitted_effect",
            "stale_capsule",
            "wrong_root",
            "heuristic_as_exact",
            "opaque_as_exact",
            "selection_miss",
            "observation_complete",
        ):
            object.__setattr__(self, flag, _bool(getattr(self, flag), flag))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CAPSULE_ADEQUACY_SUBJECT_SCHEMA,
            "subject_id": self.subject_id,
            "profile_id": self.profile_id,
            "claims": [item.identity_payload() for item in self.claims],
            "reachable_behaviors": [
                item.identity_payload() for item in self.reachable_behaviors
            ],
            "detectors": [item.identity_payload() for item in self.detectors],
            "false_assurance_evidence": [
                item.identity_payload() for item in self.false_assurance_evidence
            ],
            "uncertainty": [item.identity_payload() for item in self.uncertainty],
            "scope": self.scope.identity_payload(),
            "gap_signals": list(self.gap_signals),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "capsule_cids": list(self.capsule_cids),
            "omitted_edge_ids": list(self.omitted_edge_ids),
            "omitted_dependency": self.omitted_dependency,
            "omitted_config": self.omitted_config,
            "omitted_fixture": self.omitted_fixture,
            "omitted_exception": self.omitted_exception,
            "omitted_effect": self.omitted_effect,
            "stale_capsule": self.stale_capsule,
            "wrong_root": self.wrong_root,
            "heuristic_as_exact": self.heuristic_as_exact,
            "opaque_as_exact": self.opaque_as_exact,
            "selection_miss": self.selection_miss,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def subject_observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["claims"] = [item.to_dict() for item in self.claims]
        value["reachable_behaviors"] = [
            item.to_dict() for item in self.reachable_behaviors
        ]
        value["detectors"] = [item.to_dict() for item in self.detectors]
        value["false_assurance_evidence"] = [
            item.to_dict() for item in self.false_assurance_evidence
        ]
        value["uncertainty"] = [item.to_dict() for item in self.uncertainty]
        value["scope"] = self.scope.to_dict()
        value["source_spans"] = [span.to_dict() for span in self.source_spans]
        value["minimized_evidence"] = self.minimized_evidence.to_dict()
        value["subject_observation_cid"] = self.subject_observation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapsuleAdequacySubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("subject_observation_cid")
        if payload.pop("schema") != CAPSULE_ADEQUACY_SUBJECT_SCHEMA:
            raise AdequacyError("unsupported CapsuleAdequacySubject schema version")
        result = cls(**payload)  # type: ignore[arg-type]
        if claimed != result.subject_observation_cid:
            raise AdequacyError(
                "CapsuleAdequacySubject subject_observation_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Subject normalizers
# ---------------------------------------------------------------------------


def _normalize_test_subject(
    value: TestAdequacySubject | Mapping[str, Any],
    name: str = "subject",
) -> TestAdequacySubject:
    if isinstance(value, TestAdequacySubject):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "subject_observation_cid" in value:
            return TestAdequacySubject.from_dict(value)
        return TestAdequacySubject(**dict(value))  # type: ignore[arg-type]
    raise AdequacyError(f"{name} must be TestAdequacySubject or mapping")


def _normalize_proof_subject(
    value: ProofAdequacySubject | Mapping[str, Any],
    name: str = "subject",
) -> ProofAdequacySubject:
    if isinstance(value, ProofAdequacySubject):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "subject_observation_cid" in value:
            return ProofAdequacySubject.from_dict(value)
        return ProofAdequacySubject(**dict(value))  # type: ignore[arg-type]
    raise AdequacyError(f"{name} must be ProofAdequacySubject or mapping")


def _normalize_policy_subject(
    value: PolicyAdequacySubject | Mapping[str, Any],
    name: str = "subject",
) -> PolicyAdequacySubject:
    if isinstance(value, PolicyAdequacySubject):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "subject_observation_cid" in value:
            return PolicyAdequacySubject.from_dict(value)
        return PolicyAdequacySubject(**dict(value))  # type: ignore[arg-type]
    raise AdequacyError(f"{name} must be PolicyAdequacySubject or mapping")


def _normalize_capsule_subject(
    value: CapsuleAdequacySubject | Mapping[str, Any],
    name: str = "subject",
) -> CapsuleAdequacySubject:
    if isinstance(value, CapsuleAdequacySubject):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "subject_observation_cid" in value:
            return CapsuleAdequacySubject.from_dict(value)
        return CapsuleAdequacySubject(**dict(value))  # type: ignore[arg-type]
    raise AdequacyError(f"{name} must be CapsuleAdequacySubject or mapping")


# ---------------------------------------------------------------------------
# Gap / verdict derivation
# ---------------------------------------------------------------------------


def _detector_ids_by_role(
    detectors: Sequence[DetectorAdequacyBinding],
    role: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(item.detector_id for item in detectors if item.role == role)
    )


def _required_unexercised_behaviors(
    behaviors: Sequence[ReachableBehaviorBinding],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            item.behavior_id
            for item in behaviors
            if item.required and item.reachable and not item.exercised
        )
    )


def _blocking_uncertainty(
    uncertainty: Sequence[UncertaintyBinding],
) -> tuple[UncertaintyBinding, ...]:
    return tuple(item for item in uncertainty if item.blocks_adequacy)


def _derive_test_gaps(subject: TestAdequacySubject) -> tuple[str, ...]:
    gaps: set[str] = set(subject.gap_signals)
    if subject.weak_assertions:
        gaps.add(TestAdequacyGapClass.WEAK_ASSERTION.value)
    if subject.tautology_assertions:
        gaps.add(TestAdequacyGapClass.TAUTOLOGY.value)
    if subject.uncalled_targets:
        gaps.add(TestAdequacyGapClass.UNCALLED_TARGET.value)
    if subject.permanent_skips:
        gaps.add(TestAdequacyGapClass.PERMANENT_SKIP.value)
    if subject.mock_bypasses:
        gaps.add(TestAdequacyGapClass.MOCK_BYPASS.value)
    if subject.fixture_bypasses:
        gaps.add(TestAdequacyGapClass.FIXTURE_BYPASS.value)
    if subject.success_before_effect:
        gaps.add(TestAdequacyGapClass.SUCCESS_BEFORE_EFFECT.value)
    if subject.type_only_coverage:
        gaps.add(TestAdequacyGapClass.TYPE_ONLY_COVERAGE.value)
    if subject.selection_misses:
        gaps.add(TestAdequacyGapClass.SELECTION_MISS.value)
    missing = _detector_ids_by_role(
        subject.detectors, DetectorAdequacyRole.MISSING.value
    )
    if missing:
        # Missing detectors without a more specific flag still surface as
        # missing behavior assertion when required behaviors are unexercised.
        unexercised = _required_unexercised_behaviors(subject.reachable_behaviors)
        if unexercised:
            gaps.add(TestAdequacyGapClass.MISSING_BEHAVIOR_ASSERTION.value)
        elif not gaps:
            gaps.add(TestAdequacyGapClass.MISSING_BEHAVIOR_ASSERTION.value)
    unexercised = _required_unexercised_behaviors(subject.reachable_behaviors)
    if unexercised and TestAdequacyGapClass.UNCALLED_TARGET.value not in gaps:
        gaps.add(TestAdequacyGapClass.MISSING_BEHAVIOR_ASSERTION.value)
    if subject.false_assurance_evidence and not gaps:
        # False assurance without a more specific gap still fails adequacy.
        gaps.add(TestAdequacyGapClass.WEAK_ASSERTION.value)
    return tuple(sorted(gaps))


def _derive_proof_gaps(subject: ProofAdequacySubject) -> tuple[str, ...]:
    gaps: set[str] = set(subject.gap_signals)
    if subject.missing_obligation_ids:
        gaps.add(ProofAdequacyGapClass.MISSING_OBLIGATION.value)
    if subject.vacuous_proof:
        gaps.add(ProofAdequacyGapClass.VACUOUS_PROOF.value)
    if subject.unsatisfiable_antecedent:
        gaps.add(ProofAdequacyGapClass.UNSATISFIABLE_ANTECEDENT.value)
    if subject.unreachable_state:
        gaps.add(ProofAdequacyGapClass.UNREACHABLE_STATE.value)
    if subject.assumed_not_proven:
        gaps.add(ProofAdequacyGapClass.ASSUMED_NOT_PROVEN.value)
    if subject.omitted_behavior:
        gaps.add(ProofAdequacyGapClass.OMITTED_BEHAVIOR.value)
    if subject.stale_proof_unit:
        gaps.add(ProofAdequacyGapClass.STALE_PROOF_UNIT.value)
    unexercised = _required_unexercised_behaviors(subject.reachable_behaviors)
    if unexercised:
        gaps.add(ProofAdequacyGapClass.OMITTED_BEHAVIOR.value)
    if subject.false_assurance_evidence and not gaps:
        gaps.add(ProofAdequacyGapClass.MISSING_OBLIGATION.value)
    return tuple(sorted(gaps))


def _derive_policy_gaps(subject: PolicyAdequacySubject) -> tuple[str, ...]:
    gaps: set[str] = set(subject.gap_signals)
    if subject.missing_constraint_ids:
        gaps.add(PolicyAdequacyGapClass.MISSING_CONSTRAINT.value)
    if subject.unreachable_rule:
        gaps.add(PolicyAdequacyGapClass.UNREACHABLE_RULE.value)
    if subject.shadowed_prohibition:
        gaps.add(PolicyAdequacyGapClass.SHADOWED_PROHIBITION.value)
    if subject.dominating_default:
        gaps.add(PolicyAdequacyGapClass.DOMINATING_DEFAULT.value)
    if subject.impossible_obligation:
        gaps.add(PolicyAdequacyGapClass.IMPOSSIBLE_OBLIGATION.value)
    if subject.obsolete_interface:
        gaps.add(PolicyAdequacyGapClass.OBSOLETE_INTERFACE.value)
    if subject.stale_policy:
        gaps.add(PolicyAdequacyGapClass.STALE_POLICY.value)
    unexercised = _required_unexercised_behaviors(subject.reachable_behaviors)
    if unexercised:
        gaps.add(PolicyAdequacyGapClass.UNREACHABLE_RULE.value)
    if subject.false_assurance_evidence and not gaps:
        gaps.add(PolicyAdequacyGapClass.MISSING_CONSTRAINT.value)
    return tuple(sorted(gaps))


def _derive_capsule_gaps(subject: CapsuleAdequacySubject) -> tuple[str, ...]:
    gaps: set[str] = set(subject.gap_signals)
    if subject.omitted_edge_ids or subject.omitted_dependency:
        gaps.add(CapsuleAdequacyGapClass.OMITTED_DEPENDENCY.value)
    if subject.omitted_config:
        gaps.add(CapsuleAdequacyGapClass.OMITTED_CONFIG.value)
    if subject.omitted_fixture:
        gaps.add(CapsuleAdequacyGapClass.OMITTED_FIXTURE.value)
    if subject.omitted_exception:
        gaps.add(CapsuleAdequacyGapClass.OMITTED_EXCEPTION.value)
    if subject.omitted_effect:
        gaps.add(CapsuleAdequacyGapClass.OMITTED_EFFECT.value)
    if subject.stale_capsule:
        gaps.add(CapsuleAdequacyGapClass.STALE_CAPSULE.value)
    if subject.wrong_root:
        gaps.add(CapsuleAdequacyGapClass.WRONG_ROOT.value)
    if subject.heuristic_as_exact:
        gaps.add(CapsuleAdequacyGapClass.HEURISTIC_AS_EXACT.value)
    if subject.opaque_as_exact:
        gaps.add(CapsuleAdequacyGapClass.OPAQUE_AS_EXACT.value)
    if subject.selection_miss:
        gaps.add(CapsuleAdequacyGapClass.SELECTION_MISS.value)
    unexercised = _required_unexercised_behaviors(subject.reachable_behaviors)
    if unexercised and CapsuleAdequacyGapClass.OMITTED_EFFECT.value not in gaps:
        gaps.add(CapsuleAdequacyGapClass.OMITTED_EFFECT.value)
    if subject.false_assurance_evidence and not gaps:
        gaps.add(CapsuleAdequacyGapClass.OMITTED_DEPENDENCY.value)
    return tuple(sorted(gaps))


def _derive_verdict(
    *,
    gaps: Sequence[str],
    covered_count: int,
    missing_count: int,
    blocking_uncertainty: Sequence[UncertaintyBinding],
    false_assurance_count: int,
) -> str:
    """Derive an adequacy verdict without consulting any score.

    Scores are never an input. False-assurance evidence and gaps dominate.
    Blocking uncertainty without concrete gaps yields ``inconclusive``.
    """

    if blocking_uncertainty and not gaps and false_assurance_count == 0:
        kinds = {item.kind for item in blocking_uncertainty}
        if UncertaintyKind.INCOMPLETE_OBSERVATION.value in kinds:
            return AdequacyVerdict.UNKNOWN.value
        if UncertaintyKind.SCORE_ONLY_SIGNAL.value in kinds:
            # Score-only signals never become adequate; they stay inconclusive.
            return AdequacyVerdict.INCONCLUSIVE.value
        return AdequacyVerdict.INCONCLUSIVE.value

    if not gaps and false_assurance_count == 0 and not blocking_uncertainty:
        return AdequacyVerdict.ADEQUATE.value

    # Any concrete gap or false-assurance evidence is inadequate or partial.
    if gaps or false_assurance_count > 0:
        if covered_count > 0 and (missing_count > 0 or gaps):
            # Partial coverage with residual gaps.
            if covered_count > 0 and missing_count == 0 and len(gaps) <= 2:
                return AdequacyVerdict.PARTIAL.value
            if covered_count > 0 and missing_count > 0:
                return AdequacyVerdict.PARTIAL.value
            return AdequacyVerdict.INADEQUATE.value
        return AdequacyVerdict.INADEQUATE.value

    return AdequacyVerdict.INCONCLUSIVE.value


def _finalize_gaps_and_verdict(
    *,
    gaps: Sequence[str],
    covered_count: int,
    missing_count: int,
    blocking_uncertainty: Sequence[UncertaintyBinding],
    false_assurance_count: int,
) -> tuple[str, tuple[str, ...]]:
    verdict = _derive_verdict(
        gaps=gaps,
        covered_count=covered_count,
        missing_count=missing_count,
        blocking_uncertainty=blocking_uncertainty,
        false_assurance_count=false_assurance_count,
    )
    if verdict == AdequacyVerdict.ADEQUATE.value:
        return verdict, (TestAdequacyGapClass.NONE.value,)
    if not gaps:
        # Inconclusive / unknown with no concrete gap class still needs a
        # non-none residual marker for contract consistency on inadequate-
        # family verdicts. Use the surface-agnostic approach: leave a single
        # placeholder only when inadequate/partial requires non-none.
        if verdict in {
            AdequacyVerdict.INADEQUATE.value,
            AdequacyVerdict.PARTIAL.value,
        }:
            # Should not happen given _derive_verdict; fail closed.
            raise AdequacyError(
                "inadequate/partial verdict requires at least one gap class"
            )
        # For unknown/inconclusive, profiles require gap_classes nonempty and
        # consistent. Contract: adequate requires ['none']; inadequate/partial
        # require non-none; unknown/inconclusive admit non-none or need care.
        # analysis_contracts only special-cases adequate/inadequate/partial.
        # unknown/inconclusive with ['none'] is allowed by contract validators.
        return verdict, (TestAdequacyGapClass.NONE.value,)
    return verdict, tuple(sorted(gaps))


def _binding_metadata(
    *,
    subject_id: str,
    subject_observation_cid: str,
    surface: str,
    claims: Sequence[AdequacyClaimBinding],
    behaviors: Sequence[ReachableBehaviorBinding],
    detectors: Sequence[DetectorAdequacyBinding],
    false_assurance: Sequence[FalseAssuranceEvidenceBinding],
    uncertainty: Sequence[UncertaintyBinding],
    scope: AdequacyScopeBinding,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Metadata that re-states every bound adequacy facet without scores."""

    meta: dict[str, Any] = {
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "surface": surface,
        "subject_id": subject_id,
        "subject_observation_cid": subject_observation_cid,
        "claim_ids": [item.claim_id for item in claims],
        "claim_texts": [item.claim_text for item in claims],
        "reachable_behavior_ids": [item.behavior_id for item in behaviors],
        "exercised_behavior_ids": [
            item.behavior_id for item in behaviors if item.exercised
        ],
        "required_unexercised_behavior_ids": list(
            _required_unexercised_behaviors(behaviors)
        ),
        "detector_ids": [item.detector_id for item in detectors],
        "covered_detector_ids": list(
            _detector_ids_by_role(detectors, DetectorAdequacyRole.COVERED.value)
        ),
        "missing_detector_ids": list(
            _detector_ids_by_role(detectors, DetectorAdequacyRole.MISSING.value)
        ),
        "false_assurance_evidence_ids": [
            item.evidence_id for item in false_assurance
        ],
        "false_assurance_evidence_cids": [
            item.evidence_cid for item in false_assurance
        ],
        "uncertainty_ids": [item.uncertainty_id for item in uncertainty],
        "blocking_uncertainty_ids": [
            item.uncertainty_id for item in uncertainty if item.blocks_adequacy
        ],
        "scope_id": scope.scope_id,
        "scope_binding_cid": scope.binding_cid,
        "scope_target_symbol_ids": list(scope.target_symbol_ids),
        "score_establishes_correctness": False,
        "bindings_complete": True,
    }
    if extra:
        # Reject score authority in caller extras before merge so a truthy
        # forbidden key cannot be silently dropped by reserved keys.
        _reject_score_authority(dict(extra), "builder.metadata")
        for key, value in extra.items():
            if key in meta and key not in {"notes"}:
                continue
            meta[key] = value
    _reject_score_authority(meta, "profile.metadata")
    return meta


# ---------------------------------------------------------------------------
# Build result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AdequacyProfileBuildResult:
    """Sealed envelope around one constructed adequacy profile.

    Interface: ``AdequacyProfileBuildResult@1``
    """

    interface_id: str
    surface: str
    subject_id: str
    subject_observation_cid: str
    profile_id: str
    profile_cid: str
    verdict: str
    gap_classes: Sequence[str]
    claim_ids: Sequence[str]
    reachable_behavior_ids: Sequence[str]
    detector_ids: Sequence[str]
    false_assurance_evidence_ids: Sequence[str]
    uncertainty_ids: Sequence[str]
    scope_id: str
    score_establishes_correctness: bool
    profile: Mapping[str, Any]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "surface",
            "subject_id",
            "subject_observation_cid",
            "profile_id",
            "profile_cid",
            "verdict",
            "gap_classes",
            "claim_ids",
            "reachable_behavior_ids",
            "detector_ids",
            "false_assurance_evidence_ids",
            "uncertainty_ids",
            "scope_id",
            "score_establishes_correctness",
            "profile",
            "notes",
            "metadata",
            "result_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "interface_id", _text(self.interface_id, "interface_id")
        )
        surface = _token(self.surface, "surface")
        if surface not in _SURFACE_KINDS:
            raise AdequacyError(f"surface={surface!r} is not an admitted surface")
        object.__setattr__(self, "surface", surface)
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(
            self,
            "subject_observation_cid",
            _cid(self.subject_observation_cid, "subject_observation_cid"),
        )
        object.__setattr__(self, "profile_id", _token(self.profile_id, "profile_id"))
        object.__setattr__(self, "profile_cid", _cid(self.profile_cid, "profile_cid"))
        object.__setattr__(
            self, "verdict", _enum(self.verdict, AdequacyVerdict, "verdict")
        )
        object.__setattr__(
            self,
            "gap_classes",
            _unique_sorted_tokens(list(self.gap_classes), "gap_classes", maximum=MAX_GAPS),
        )
        object.__setattr__(
            self,
            "claim_ids",
            _unique_sorted_tokens(list(self.claim_ids), "claim_ids", maximum=MAX_CLAIMS),
        )
        object.__setattr__(
            self,
            "reachable_behavior_ids",
            _unique_sorted_tokens(
                list(self.reachable_behavior_ids),
                "reachable_behavior_ids",
                maximum=MAX_BEHAVIORS,
            ),
        )
        object.__setattr__(
            self,
            "detector_ids",
            _unique_sorted_tokens(
                list(self.detector_ids), "detector_ids", maximum=MAX_DETECTORS
            ),
        )
        object.__setattr__(
            self,
            "false_assurance_evidence_ids",
            _unique_sorted_tokens(
                list(self.false_assurance_evidence_ids),
                "false_assurance_evidence_ids",
                maximum=MAX_EVIDENCE,
            ),
        )
        object.__setattr__(
            self,
            "uncertainty_ids",
            _unique_sorted_tokens(
                list(self.uncertainty_ids),
                "uncertainty_ids",
                maximum=MAX_UNCERTAINTY,
            ),
        )
        object.__setattr__(self, "scope_id", _token(self.scope_id, "scope_id"))
        score_flag = _bool(
            self.score_establishes_correctness, "score_establishes_correctness"
        )
        if score_flag:
            raise AdequacyError(
                "score_establishes_correctness must be false; scores never "
                "establish correctness"
            )
        object.__setattr__(self, "score_establishes_correctness", False)
        if not isinstance(self.profile, Mapping):
            raise AdequacyError("profile must be a mapping")
        object.__setattr__(
            self, "profile", _sealed_profile_mapping(self.profile, "profile")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ADEQUACY_PROFILE_BUILD_RESULT_SCHEMA,
            "interface_id": self.interface_id,
            "surface": self.surface,
            "subject_id": self.subject_id,
            "subject_observation_cid": self.subject_observation_cid,
            "profile_id": self.profile_id,
            "profile_cid": self.profile_cid,
            "verdict": self.verdict,
            "gap_classes": list(self.gap_classes),
            "claim_ids": list(self.claim_ids),
            "reachable_behavior_ids": list(self.reachable_behavior_ids),
            "detector_ids": list(self.detector_ids),
            "false_assurance_evidence_ids": list(self.false_assurance_evidence_ids),
            "uncertainty_ids": list(self.uncertainty_ids),
            "scope_id": self.scope_id,
            "score_establishes_correctness": self.score_establishes_correctness,
            "profile": _thaw_structured(self.profile),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["result_cid"] = self.result_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AdequacyProfileBuildResult":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("result_cid")
        if payload.pop("schema") != ADEQUACY_PROFILE_BUILD_RESULT_SCHEMA:
            raise AdequacyError(
                "unsupported AdequacyProfileBuildResult schema version"
            )
        result = cls(**payload)  # type: ignore[arg-type]
        if claimed != result.result_cid:
            raise AdequacyError(
                "AdequacyProfileBuildResult result_cid identity mismatch"
            )
        return result


def verify_adequacy_profile_build_result_identity(
    result: AdequacyProfileBuildResult | Mapping[str, Any],
) -> AdequacyProfileBuildResult:
    """Decode-and-recompute identity for a sealed build result."""

    if isinstance(result, AdequacyProfileBuildResult):
        restored = AdequacyProfileBuildResult.from_dict(result.to_dict())
        if restored.result_cid != result.result_cid:
            raise AdequacyError("AdequacyProfileBuildResult identity mismatch")
        return restored
    if isinstance(result, Mapping):
        return AdequacyProfileBuildResult.from_dict(result)
    raise AdequacyError(
        "result must be AdequacyProfileBuildResult or mapping"
    )


def _build_result(
    *,
    interface_id: str,
    surface: str,
    subject_id: str,
    subject_observation_cid: str,
    profile: (
        TestAdequacyProfile
        | ProofAdequacyProfile
        | PolicyAdequacyProfile
        | CapsuleAdequacyProfile
    ),
    claim_ids: Sequence[str],
    behavior_ids: Sequence[str],
    detector_ids: Sequence[str],
    false_assurance_ids: Sequence[str],
    uncertainty_ids: Sequence[str],
    scope_id: str,
    notes: str | None,
    metadata: Mapping[str, Any],
) -> AdequacyProfileBuildResult:
    return AdequacyProfileBuildResult(
        interface_id=interface_id,
        surface=surface,
        subject_id=subject_id,
        subject_observation_cid=subject_observation_cid,
        profile_id=profile.profile_id,
        profile_cid=profile.profile_cid,
        verdict=profile.verdict,
        gap_classes=tuple(profile.gap_classes),
        claim_ids=tuple(claim_ids),
        reachable_behavior_ids=tuple(behavior_ids),
        detector_ids=tuple(detector_ids),
        false_assurance_evidence_ids=tuple(false_assurance_ids),
        uncertainty_ids=tuple(uncertainty_ids),
        scope_id=scope_id,
        score_establishes_correctness=False,
        profile=profile.to_dict(),
        notes=notes,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_test_adequacy_profile(
    subject: TestAdequacySubject | Mapping[str, Any],
    header: AssuranceArtifactHeader | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AdequacyProfileBuildResult:
    """Build a sealed test-surface adequacy profile.

    Interface: ``build_test_adequacy_profile@1``

    Binds claims, reachable behavior, detectors, false-assurance evidence,
    uncertainty, gaps, and scope. Rejects score-as-correctness authority.
    Incomplete observation fails closed.
    """

    sealed = _normalize_test_subject(subject)
    if not sealed.observation_complete:
        raise AdequacyError(
            "build_test_adequacy_profile fails closed when observation_complete "
            "is false"
        )
    base_header = _header(header)
    profile_header = _profile_header(
        base_header,
        artifact_kind="test_adequacy_profile",
        interface_id=BUILD_TEST_ADEQUACY_PROFILE_INTERFACE,
        symbol_ids=sealed.scope.target_symbol_ids,
    )

    gaps = _derive_test_gaps(sealed)
    covered = _detector_ids_by_role(
        sealed.detectors, DetectorAdequacyRole.COVERED.value
    )
    missing = _detector_ids_by_role(
        sealed.detectors, DetectorAdequacyRole.MISSING.value
    )
    blocking = _blocking_uncertainty(sealed.uncertainty)
    verdict, gap_classes = _finalize_gaps_and_verdict(
        gaps=gaps,
        covered_count=len(covered),
        missing_count=len(missing),
        blocking_uncertainty=blocking,
        false_assurance_count=len(sealed.false_assurance_evidence),
    )

    profile_meta = _binding_metadata(
        subject_id=sealed.subject_id,
        subject_observation_cid=sealed.subject_observation_cid,
        surface="test",
        claims=sealed.claims,
        behaviors=sealed.reachable_behaviors,
        detectors=sealed.detectors,
        false_assurance=sealed.false_assurance_evidence,
        uncertainty=sealed.uncertainty,
        scope=sealed.scope,
        extra=dict(metadata or {}),
    )
    profile_meta["builder_interface"] = BUILD_TEST_ADEQUACY_PROFILE_INTERFACE

    profile = TestAdequacyProfile(
        header=profile_header,
        profile_id=sealed.profile_id,
        target_symbol_ids=sealed.scope.target_symbol_ids,
        verdict=verdict,
        gap_classes=gap_classes,
        covered_detector_ids=covered,
        missing_detector_ids=missing,
        minimized_evidence=sealed.minimized_evidence,
        notes=notes if notes is not None else sealed.notes,
        metadata=profile_meta,
    )

    return _build_result(
        interface_id=BUILD_TEST_ADEQUACY_PROFILE_INTERFACE,
        surface="test",
        subject_id=sealed.subject_id,
        subject_observation_cid=sealed.subject_observation_cid,
        profile=profile,
        claim_ids=[item.claim_id for item in sealed.claims],
        behavior_ids=[item.behavior_id for item in sealed.reachable_behaviors],
        detector_ids=[item.detector_id for item in sealed.detectors],
        false_assurance_ids=[
            item.evidence_id for item in sealed.false_assurance_evidence
        ],
        uncertainty_ids=[item.uncertainty_id for item in sealed.uncertainty],
        scope_id=sealed.scope.scope_id,
        notes=notes if notes is not None else sealed.notes,
        metadata={
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "surface": "test",
        },
    )


def build_proof_adequacy_profile(
    subject: ProofAdequacySubject | Mapping[str, Any],
    header: AssuranceArtifactHeader | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AdequacyProfileBuildResult:
    """Build a sealed proof-surface adequacy profile.

    Interface: ``build_proof_adequacy_profile@1``
    """

    sealed = _normalize_proof_subject(subject)
    if not sealed.observation_complete:
        raise AdequacyError(
            "build_proof_adequacy_profile fails closed when observation_complete "
            "is false"
        )
    base_header = _header(header)
    profile_header = _profile_header(
        base_header,
        artifact_kind="proof_adequacy_profile",
        interface_id=BUILD_PROOF_ADEQUACY_PROFILE_INTERFACE,
        symbol_ids=sealed.scope.target_symbol_ids,
    )

    gaps = _derive_proof_gaps(sealed)
    covered = _detector_ids_by_role(
        sealed.detectors, DetectorAdequacyRole.COVERED.value
    )
    missing = _detector_ids_by_role(
        sealed.detectors, DetectorAdequacyRole.MISSING.value
    )
    # Treat missing obligations as missing detector-equivalents for partiality.
    missing_count = len(missing) + len(sealed.missing_obligation_ids)
    blocking = _blocking_uncertainty(sealed.uncertainty)
    verdict, gap_classes = _finalize_gaps_and_verdict(
        gaps=gaps,
        covered_count=len(covered) + len(sealed.proof_unit_cids),
        missing_count=missing_count,
        blocking_uncertainty=blocking,
        false_assurance_count=len(sealed.false_assurance_evidence),
    )

    profile_meta = _binding_metadata(
        subject_id=sealed.subject_id,
        subject_observation_cid=sealed.subject_observation_cid,
        surface="proof",
        claims=sealed.claims,
        behaviors=sealed.reachable_behaviors,
        detectors=sealed.detectors,
        false_assurance=sealed.false_assurance_evidence,
        uncertainty=sealed.uncertainty,
        scope=sealed.scope,
        extra={
            **dict(metadata or {}),
            "proof_unit_cids": list(sealed.proof_unit_cids),
            "missing_obligation_ids": list(sealed.missing_obligation_ids),
        },
    )
    profile_meta["builder_interface"] = BUILD_PROOF_ADEQUACY_PROFILE_INTERFACE

    # Prefer header proof units when subject omits them.
    proof_units = sealed.proof_unit_cids or tuple(base_header.proof_unit_cids)

    profile = ProofAdequacyProfile(
        header=profile_header,
        profile_id=sealed.profile_id,
        target_symbol_ids=sealed.scope.target_symbol_ids,
        verdict=verdict,
        gap_classes=gap_classes,
        proof_unit_cids=proof_units,
        missing_obligation_ids=sealed.missing_obligation_ids,
        minimized_evidence=sealed.minimized_evidence,
        notes=notes if notes is not None else sealed.notes,
        metadata=profile_meta,
    )

    return _build_result(
        interface_id=BUILD_PROOF_ADEQUACY_PROFILE_INTERFACE,
        surface="proof",
        subject_id=sealed.subject_id,
        subject_observation_cid=sealed.subject_observation_cid,
        profile=profile,
        claim_ids=[item.claim_id for item in sealed.claims],
        behavior_ids=[item.behavior_id for item in sealed.reachable_behaviors],
        detector_ids=[item.detector_id for item in sealed.detectors],
        false_assurance_ids=[
            item.evidence_id for item in sealed.false_assurance_evidence
        ],
        uncertainty_ids=[item.uncertainty_id for item in sealed.uncertainty],
        scope_id=sealed.scope.scope_id,
        notes=notes if notes is not None else sealed.notes,
        metadata={
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "surface": "proof",
        },
    )


def build_policy_adequacy_profile(
    subject: PolicyAdequacySubject | Mapping[str, Any],
    header: AssuranceArtifactHeader | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AdequacyProfileBuildResult:
    """Build a sealed policy-surface adequacy profile.

    Interface: ``build_policy_adequacy_profile@1``
    """

    sealed = _normalize_policy_subject(subject)
    if not sealed.observation_complete:
        raise AdequacyError(
            "build_policy_adequacy_profile fails closed when observation_complete "
            "is false"
        )
    base_header = _header(header)
    profile_header = _profile_header(
        base_header,
        artifact_kind="policy_adequacy_profile",
        interface_id=BUILD_POLICY_ADEQUACY_PROFILE_INTERFACE,
        symbol_ids=sealed.scope.target_symbol_ids,
    )

    gaps = _derive_policy_gaps(sealed)
    covered = _detector_ids_by_role(
        sealed.detectors, DetectorAdequacyRole.COVERED.value
    )
    missing = _detector_ids_by_role(
        sealed.detectors, DetectorAdequacyRole.MISSING.value
    )
    missing_count = len(missing) + len(sealed.missing_constraint_ids)
    blocking = _blocking_uncertainty(sealed.uncertainty)
    verdict, gap_classes = _finalize_gaps_and_verdict(
        gaps=gaps,
        covered_count=len(covered) + len(sealed.policy_cids),
        missing_count=missing_count,
        blocking_uncertainty=blocking,
        false_assurance_count=len(sealed.false_assurance_evidence),
    )

    profile_meta = _binding_metadata(
        subject_id=sealed.subject_id,
        subject_observation_cid=sealed.subject_observation_cid,
        surface="policy",
        claims=sealed.claims,
        behaviors=sealed.reachable_behaviors,
        detectors=sealed.detectors,
        false_assurance=sealed.false_assurance_evidence,
        uncertainty=sealed.uncertainty,
        scope=sealed.scope,
        extra={
            **dict(metadata or {}),
            "policy_cids": list(sealed.policy_cids),
            "missing_constraint_ids": list(sealed.missing_constraint_ids),
        },
    )
    profile_meta["builder_interface"] = BUILD_POLICY_ADEQUACY_PROFILE_INTERFACE

    policy_cids = sealed.policy_cids
    if not policy_cids and base_header.provenance.policy_cid is not None:
        policy_cids = (base_header.provenance.policy_cid,)

    profile = PolicyAdequacyProfile(
        header=profile_header,
        profile_id=sealed.profile_id,
        target_symbol_ids=sealed.scope.target_symbol_ids,
        verdict=verdict,
        gap_classes=gap_classes,
        policy_cids=policy_cids,
        missing_constraint_ids=sealed.missing_constraint_ids,
        minimized_evidence=sealed.minimized_evidence,
        notes=notes if notes is not None else sealed.notes,
        metadata=profile_meta,
    )

    return _build_result(
        interface_id=BUILD_POLICY_ADEQUACY_PROFILE_INTERFACE,
        surface="policy",
        subject_id=sealed.subject_id,
        subject_observation_cid=sealed.subject_observation_cid,
        profile=profile,
        claim_ids=[item.claim_id for item in sealed.claims],
        behavior_ids=[item.behavior_id for item in sealed.reachable_behaviors],
        detector_ids=[item.detector_id for item in sealed.detectors],
        false_assurance_ids=[
            item.evidence_id for item in sealed.false_assurance_evidence
        ],
        uncertainty_ids=[item.uncertainty_id for item in sealed.uncertainty],
        scope_id=sealed.scope.scope_id,
        notes=notes if notes is not None else sealed.notes,
        metadata={
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "surface": "policy",
        },
    )


def build_capsule_adequacy_profile(
    subject: CapsuleAdequacySubject | Mapping[str, Any],
    header: AssuranceArtifactHeader | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AdequacyProfileBuildResult:
    """Build a sealed capsule-surface adequacy profile.

    Interface: ``build_capsule_adequacy_profile@1``
    """

    sealed = _normalize_capsule_subject(subject)
    if not sealed.observation_complete:
        raise AdequacyError(
            "build_capsule_adequacy_profile fails closed when "
            "observation_complete is false"
        )
    base_header = _header(header)
    profile_header = _profile_header(
        base_header,
        artifact_kind="capsule_adequacy_profile",
        interface_id=BUILD_CAPSULE_ADEQUACY_PROFILE_INTERFACE,
        symbol_ids=sealed.scope.target_symbol_ids,
    )

    gaps = _derive_capsule_gaps(sealed)
    covered = _detector_ids_by_role(
        sealed.detectors, DetectorAdequacyRole.COVERED.value
    )
    missing = _detector_ids_by_role(
        sealed.detectors, DetectorAdequacyRole.MISSING.value
    )
    missing_count = len(missing) + len(sealed.omitted_edge_ids)
    blocking = _blocking_uncertainty(sealed.uncertainty)
    verdict, gap_classes = _finalize_gaps_and_verdict(
        gaps=gaps,
        covered_count=len(covered) + len(sealed.capsule_cids),
        missing_count=missing_count,
        blocking_uncertainty=blocking,
        false_assurance_count=len(sealed.false_assurance_evidence),
    )

    profile_meta = _binding_metadata(
        subject_id=sealed.subject_id,
        subject_observation_cid=sealed.subject_observation_cid,
        surface="capsule",
        claims=sealed.claims,
        behaviors=sealed.reachable_behaviors,
        detectors=sealed.detectors,
        false_assurance=sealed.false_assurance_evidence,
        uncertainty=sealed.uncertainty,
        scope=sealed.scope,
        extra={
            **dict(metadata or {}),
            "capsule_cids": list(sealed.capsule_cids),
            "omitted_edge_ids": list(sealed.omitted_edge_ids),
        },
    )
    profile_meta["builder_interface"] = BUILD_CAPSULE_ADEQUACY_PROFILE_INTERFACE

    capsule_cids = sealed.capsule_cids or tuple(base_header.capsule_cids)

    profile = CapsuleAdequacyProfile(
        header=profile_header,
        profile_id=sealed.profile_id,
        target_symbol_ids=sealed.scope.target_symbol_ids,
        verdict=verdict,
        gap_classes=gap_classes,
        capsule_cids=capsule_cids,
        omitted_edge_ids=sealed.omitted_edge_ids,
        minimized_evidence=sealed.minimized_evidence,
        notes=notes if notes is not None else sealed.notes,
        metadata=profile_meta,
    )

    return _build_result(
        interface_id=BUILD_CAPSULE_ADEQUACY_PROFILE_INTERFACE,
        surface="capsule",
        subject_id=sealed.subject_id,
        subject_observation_cid=sealed.subject_observation_cid,
        profile=profile,
        claim_ids=[item.claim_id for item in sealed.claims],
        behavior_ids=[item.behavior_id for item in sealed.reachable_behaviors],
        detector_ids=[item.detector_id for item in sealed.detectors],
        false_assurance_ids=[
            item.evidence_id for item in sealed.false_assurance_evidence
        ],
        uncertainty_ids=[item.uncertainty_id for item in sealed.uncertainty],
        scope_id=sealed.scope.scope_id,
        notes=notes if notes is not None else sealed.notes,
        metadata={
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "surface": "capsule",
        },
    )


# ---------------------------------------------------------------------------
# Vocabulary helpers
# ---------------------------------------------------------------------------


def detector_adequacy_roles() -> tuple[str, ...]:
    """Return the closed detector-role vocabulary in declaration order."""

    return tuple(item.value for item in DetectorAdequacyRole)


def uncertainty_kinds() -> tuple[str, ...]:
    """Return the closed uncertainty-kind vocabulary in declaration order."""

    return tuple(item.value for item in UncertaintyKind)


def false_assurance_evidence_kinds() -> tuple[str, ...]:
    """Return the closed false-assurance evidence vocabulary in declaration order."""

    return tuple(item.value for item in FalseAssuranceEvidenceKind)


def score_authority_forbidden_keys() -> tuple[str, ...]:
    """Return keys that attempt score-to-correctness conversion (sorted)."""

    return tuple(sorted(SCORE_AUTHORITY_FORBIDDEN_KEYS))


__all__ = [
    "BUILD_TEST_ADEQUACY_PROFILE_INTERFACE",
    "BUILD_PROOF_ADEQUACY_PROFILE_INTERFACE",
    "BUILD_POLICY_ADEQUACY_PROFILE_INTERFACE",
    "BUILD_CAPSULE_ADEQUACY_PROFILE_INTERFACE",
    "ADEQUACY_PROFILE_BUILD_RESULT_INTERFACE",
    "ADEQUACY_PROFILE_BUILD_RESULT_SCHEMA",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "SCORE_AUTHORITY_FORBIDDEN_KEYS",
    "AdequacyError",
    "AdequacyClaimBinding",
    "ReachableBehaviorBinding",
    "DetectorAdequacyBinding",
    "DetectorAdequacyRole",
    "FalseAssuranceEvidenceBinding",
    "FalseAssuranceEvidenceKind",
    "UncertaintyBinding",
    "UncertaintyKind",
    "AdequacyScopeBinding",
    "TestAdequacySubject",
    "ProofAdequacySubject",
    "PolicyAdequacySubject",
    "CapsuleAdequacySubject",
    "AdequacyProfileBuildResult",
    "build_test_adequacy_profile",
    "build_proof_adequacy_profile",
    "build_policy_adequacy_profile",
    "build_capsule_adequacy_profile",
    "verify_adequacy_profile_build_result_identity",
    "detector_adequacy_roles",
    "uncertainty_kinds",
    "false_assurance_evidence_kinds",
    "score_authority_forbidden_keys",
]
