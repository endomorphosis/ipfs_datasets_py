"""Survivor, gap, vacuity, detection-failure, and adequacy models (AAE-010).

Defines closed, versioned durable models for surviving-mutant reports,
assurance gaps, vacuity findings, detection failures, and test/proof/policy/
capsule adequacy profiles.

Authority rules (normative):

* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
* Records are recursively immutable, closed to unknown fields, and restricted
  to strict DAG-JSON types admitted by content identity (no floats, no host
  objects, no repr fallbacks).
* Stored CIDs are verified by decode-and-recompute, never trusted alone.
* Gap and adequacy taxonomies are closed; unknown enum values fail closed.
* Survivor and gap reports bind minimized evidence only (no full logs).
* Every vacuity finding states exactly what remains proven.
* Private material, model-written authority, and host fallbacks are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import re
import unicodedata
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceArtifactHeader,
    AssuranceBaseError,
    reject_private_model_authority_and_host_fallbacks,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

SURVIVING_MUTANT_REPORT_INTERFACE: Final[str] = "SurvivingMutantReport@1"
SURVIVING_MUTANT_REPORT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-surviving-mutant-report@1"
)
ASSURANCE_GAP_INTERFACE: Final[str] = "AssuranceGap@1"
ASSURANCE_GAP_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-gap@1"
)
VACUITY_FINDING_INTERFACE: Final[str] = "VacuityFinding@1"
VACUITY_FINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-vacuity-finding@1"
)
DETECTION_FAILURE_INTERFACE: Final[str] = "DetectionFailure@1"
DETECTION_FAILURE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-detection-failure@1"
)
TEST_ADEQUACY_PROFILE_INTERFACE: Final[str] = "TestAdequacyProfile@1"
TEST_ADEQUACY_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-test-adequacy-profile@1"
)
PROOF_ADEQUACY_PROFILE_INTERFACE: Final[str] = "ProofAdequacyProfile@1"
PROOF_ADEQUACY_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-proof-adequacy-profile@1"
)
POLICY_ADEQUACY_PROFILE_INTERFACE: Final[str] = "PolicyAdequacyProfile@1"
POLICY_ADEQUACY_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-policy-adequacy-profile@1"
)
CAPSULE_ADEQUACY_PROFILE_INTERFACE: Final[str] = "CapsuleAdequacyProfile@1"
CAPSULE_ADEQUACY_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-capsule-adequacy-profile@1"
)
SOURCE_SPAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-source-span@1"
)
MINIMIZED_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-minimized-evidence@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_ID_LIST: Final[int] = 4_096
MAX_TOKEN_LIST: Final[int] = 256
MAX_DETECTORS: Final[int] = 1_024
MAX_SPANS: Final[int] = 256
MAX_DEPENDENCY_PATH: Final[int] = 64
MAX_REVISION: Final[int] = 2**63 - 1
MAX_LINE: Final[int] = 10_000_000
MAX_COL: Final[int] = 1_000_000
MAX_PATH_CHARS: Final[int] = 1_024
MAX_COMMAND_CHARS: Final[int] = 4_096
MAX_GAPS: Final[int] = 256

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)
_REPOSITORY_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,255}$"
)
_REPO_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:[A-Za-z0-9_./@+-][A-Za-z0-9_./@+-]{0,1022})$"
)


class AnalysisContractError(AssuranceBaseError):
    """Raised when an analysis contract record is malformed or unsafe."""


# ---------------------------------------------------------------------------
# Closed enumerations — gap taxonomy (plan §5)
# ---------------------------------------------------------------------------


class AssuranceGapClass(str, Enum):
    """Closed assurance-gap taxonomy (plan §5)."""

    MISSING_TEST = "missing_test"
    WEAK_ASSERTION = "weak_assertion"
    MISSING_PROOF_OBLIGATION = "missing_proof_obligation"
    VACUOUS_PROOF = "vacuous_proof"
    MISSING_POLICY_CONSTRAINT = "missing_policy_constraint"
    STALE_OR_INCOMPLETE_DEPENDENCY_EDGE = "stale_or_incomplete_dependency_edge"
    CAPSULE_COMPLETENESS_FAILURE = "capsule_completeness_failure"
    TEST_SELECTION_FAILURE = "test_selection_failure"
    UNMODELED_SIDE_EFFECT = "unmodeled_side_effect"
    MISSING_STATE_TRANSITION_CONSTRAINT = "missing_state_transition_constraint"
    MISSING_ENVIRONMENT_BINDING = "missing_environment_binding"
    RECEIPT_AUTHENTICITY_GAP = "receipt_authenticity_gap"
    SPECIFICATION_AMBIGUITY = "specification_ambiguity"
    INTENTIONALLY_UNCONSTRAINED = "intentionally_unconstrained"
    PROBABLY_EQUIVALENT = "probably_equivalent"
    UNKNOWN = "unknown"


class GapSeverity(str, Enum):
    """Closed severity for diagnosed assurance gaps."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class SurvivorRiskClass(str, Enum):
    """Closed risk classes bound into survivor and gap reports."""

    CRITICAL_SECURITY = "critical_security"
    AUTHORIZATION = "authorization"
    DURABILITY = "durability"
    FINANCIAL_LEGAL = "financial_legal"
    DISTRIBUTED_TRANSITION = "distributed_transition"
    PROOF_RECEIPT_TRUST = "proof_receipt_trust"
    CRITICAL_INVARIANT = "critical_invariant"
    HIGH = "high"
    MEDIUM = "medium"
    LOCAL_BUG = "local_bug"
    LOW = "low"


# ---------------------------------------------------------------------------
# Closed enumerations — vacuity (plan §9)
# ---------------------------------------------------------------------------


class VacuityFamily(str, Enum):
    """Four required vacuity analysis families."""

    FORMAL_PROOF = "formal_proof"
    POLICY = "policy"
    TEST = "test"
    ZK_RECEIPT = "zk_receipt"


class VacuityKind(str, Enum):
    """Closed vacuity kind vocabulary across all four families."""

    # Formal proofs
    UNSATISFIABLE_ANTECEDENT = "unsatisfiable_antecedent"
    UNREACHABLE_MODELED_STATE = "unreachable_modeled_state"
    IMPOSSIBLE_DISCHARGE = "impossible_discharge"
    UNCONSTRAINED_RESULT = "unconstrained_result"
    OMITTED_BEHAVIOR = "omitted_behavior"
    ASSUMED_NOT_PROVEN = "assumed_not_proven"
    # Policy
    UNREACHABLE_RULE = "unreachable_rule"
    UNREACHABLE_CONFIRMATION = "unreachable_confirmation"
    SHADOWED_PROHIBITION = "shadowed_prohibition"
    IMPOSSIBLE_OBLIGATION = "impossible_obligation"
    DOMINATING_DEFAULT = "dominating_default"
    OBSOLETE_INTERFACE_REFERENCE = "obsolete_interface_reference"
    # Tests
    TAUTOLOGY = "tautology"
    TYPE_ONLY_ASSERTION = "type_only_assertion"
    NON_NULL_ONLY_ASSERTION = "non_null_only_assertion"
    BEHAVIOR_INDEPENDENT_MOCK = "behavior_independent_mock"
    UNCALLED_TARGET = "uncalled_target"
    PERMANENT_SKIP = "permanent_skip"
    BYPASSING_FIXTURE = "bypassing_fixture"
    SUCCESS_BEFORE_EFFECT_OBSERVATION = "success_before_effect_observation"
    # ZK / receipts
    UNBOUND_REQUIRED_FIELD = "unbound_required_field"
    UNBOUND_SOURCE = "unbound_source"
    UNBOUND_ENVIRONMENT = "unbound_environment"
    INCLUSION_WITHOUT_COMPLETENESS = "inclusion_without_completeness"
    CALLER_SELECTED_VERIFICATION_KEY = "caller_selected_verification_key"
    SIGNED_AGGREGATION_AS_EXECUTION = "signed_aggregation_as_execution"
    MISSING_DELTA_SEAL_UNIT = "missing_delta_seal_unit"


_VACUITY_FAMILY_KINDS: Final[Mapping[str, frozenset[str]]] = {
    VacuityFamily.FORMAL_PROOF.value: frozenset(
        {
            VacuityKind.UNSATISFIABLE_ANTECEDENT.value,
            VacuityKind.UNREACHABLE_MODELED_STATE.value,
            VacuityKind.IMPOSSIBLE_DISCHARGE.value,
            VacuityKind.UNCONSTRAINED_RESULT.value,
            VacuityKind.OMITTED_BEHAVIOR.value,
            VacuityKind.ASSUMED_NOT_PROVEN.value,
        }
    ),
    VacuityFamily.POLICY.value: frozenset(
        {
            VacuityKind.UNREACHABLE_RULE.value,
            VacuityKind.UNREACHABLE_CONFIRMATION.value,
            VacuityKind.SHADOWED_PROHIBITION.value,
            VacuityKind.IMPOSSIBLE_OBLIGATION.value,
            VacuityKind.DOMINATING_DEFAULT.value,
            VacuityKind.OBSOLETE_INTERFACE_REFERENCE.value,
        }
    ),
    VacuityFamily.TEST.value: frozenset(
        {
            VacuityKind.TAUTOLOGY.value,
            VacuityKind.TYPE_ONLY_ASSERTION.value,
            VacuityKind.NON_NULL_ONLY_ASSERTION.value,
            VacuityKind.BEHAVIOR_INDEPENDENT_MOCK.value,
            VacuityKind.UNCALLED_TARGET.value,
            VacuityKind.PERMANENT_SKIP.value,
            VacuityKind.BYPASSING_FIXTURE.value,
            VacuityKind.SUCCESS_BEFORE_EFFECT_OBSERVATION.value,
        }
    ),
    VacuityFamily.ZK_RECEIPT.value: frozenset(
        {
            VacuityKind.UNBOUND_REQUIRED_FIELD.value,
            VacuityKind.UNBOUND_SOURCE.value,
            VacuityKind.UNBOUND_ENVIRONMENT.value,
            VacuityKind.INCLUSION_WITHOUT_COMPLETENESS.value,
            VacuityKind.CALLER_SELECTED_VERIFICATION_KEY.value,
            VacuityKind.SIGNED_AGGREGATION_AS_EXECUTION.value,
            VacuityKind.MISSING_DELTA_SEAL_UNIT.value,
        }
    ),
}


# ---------------------------------------------------------------------------
# Closed enumerations — detection failure
# ---------------------------------------------------------------------------


class DetectionFailureKind(str, Enum):
    """Closed kinds of predicted-versus-observed detector failures."""

    SELECTION_MISS = "selection_miss"
    EXECUTION_MISS = "execution_miss"
    OBSERVATION_MISS = "observation_miss"
    PATH_MISS = "path_miss"
    ASSERTION_STRENGTH_FAILURE = "assertion_strength_failure"
    EXPECTED_NOT_OBSERVED = "expected_not_observed"
    UNEXPECTED_OBSERVED = "unexpected_observed"
    FULL_SUITE_REQUIRED = "full_suite_required"


# ---------------------------------------------------------------------------
# Closed enumerations — adequacy taxonomies
# ---------------------------------------------------------------------------


class AdequacyVerdict(str, Enum):
    """Closed overall adequacy verdict for a profiled surface."""

    ADEQUATE = "adequate"
    INADEQUATE = "inadequate"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    INCONCLUSIVE = "inconclusive"


class TestAdequacyGapClass(str, Enum):
    """Closed test-adequacy gap taxonomy."""

    MISSING_BEHAVIOR_ASSERTION = "missing_behavior_assertion"
    WEAK_ASSERTION = "weak_assertion"
    TAUTOLOGY = "tautology"
    UNCALLED_TARGET = "uncalled_target"
    PERMANENT_SKIP = "permanent_skip"
    MOCK_BYPASS = "mock_bypass"
    FIXTURE_BYPASS = "fixture_bypass"
    SUCCESS_BEFORE_EFFECT = "success_before_effect"
    TYPE_ONLY_COVERAGE = "type_only_coverage"
    SELECTION_MISS = "selection_miss"
    NONE = "none"


class ProofAdequacyGapClass(str, Enum):
    """Closed proof-adequacy gap taxonomy."""

    MISSING_OBLIGATION = "missing_obligation"
    VACUOUS_PROOF = "vacuous_proof"
    UNSATISFIABLE_ANTECEDENT = "unsatisfiable_antecedent"
    UNREACHABLE_STATE = "unreachable_state"
    ASSUMED_NOT_PROVEN = "assumed_not_proven"
    OMITTED_BEHAVIOR = "omitted_behavior"
    STALE_PROOF_UNIT = "stale_proof_unit"
    NONE = "none"


class PolicyAdequacyGapClass(str, Enum):
    """Closed policy-adequacy gap taxonomy."""

    MISSING_CONSTRAINT = "missing_constraint"
    UNREACHABLE_RULE = "unreachable_rule"
    SHADOWED_PROHIBITION = "shadowed_prohibition"
    DOMINATING_DEFAULT = "dominating_default"
    IMPOSSIBLE_OBLIGATION = "impossible_obligation"
    OBSOLETE_INTERFACE = "obsolete_interface"
    STALE_POLICY = "stale_policy"
    NONE = "none"


class CapsuleAdequacyGapClass(str, Enum):
    """Closed capsule-adequacy gap taxonomy."""

    OMITTED_DEPENDENCY = "omitted_dependency"
    OMITTED_CONFIG = "omitted_config"
    OMITTED_FIXTURE = "omitted_fixture"
    OMITTED_EXCEPTION = "omitted_exception"
    OMITTED_EFFECT = "omitted_effect"
    STALE_CAPSULE = "stale_capsule"
    WRONG_ROOT = "wrong_root"
    HEURISTIC_AS_EXACT = "heuristic_as_exact"
    OPAQUE_AS_EXACT = "opaque_as_exact"
    SELECTION_MISS = "selection_miss"
    NONE = "none"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise AnalysisContractError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise AnalysisContractError(f"{name} must be trimmed NFC text")
    if len(value) > maximum or any(not char.isprintable() for char in value):
        raise AnalysisContractError(f"{name} contains invalid text")
    return value


def _optional_text(
    value: Any,
    name: str,
    *,
    maximum: int = MAX_TEXT_CHARS,
) -> str | None:
    if value is None:
        return None
    return _text(value, name, maximum=maximum)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise AnalysisContractError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise AnalysisContractError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise AnalysisContractError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name)
    if _VERSION_RE.fullmatch(text) is None:
        raise AnalysisContractError(
            f"{name} must be a version token matching {_VERSION_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise AnalysisContractError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


def _repository_id(value: Any, name: str = "repository_id") -> str:
    text = _text(value, name)
    if _REPOSITORY_ID_RE.fullmatch(text) is None:
        raise AnalysisContractError(
            f"{name} must be a repository identity matching "
            f"{_REPOSITORY_ID_RE.pattern}"
        )
    return text


def _repo_path(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) > MAX_PATH_CHARS:
        raise AnalysisContractError(f"{name} exceeds maximum path length")
    if text.startswith("/") or text.startswith("\\"):
        raise AnalysisContractError(f"{name} rejects absolute paths")
    if ".." in text.split("/"):
        raise AnalysisContractError(f"{name} rejects parent-directory traversal")
    if _REPO_PATH_RE.fullmatch(text) is None:
        raise AnalysisContractError(f"{name} must be a relative repository path")
    return text


def _nonneg_int(value: Any, name: str, *, maximum: int = MAX_REVISION) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise AnalysisContractError(f"{name} must be a nonnegative integer")
    if value > maximum:
        raise AnalysisContractError(f"{name} exceeds maximum")
    return value


def _pos_int(value: Any, name: str, *, maximum: int = MAX_REVISION) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1:
        raise AnalysisContractError(f"{name} must be a positive integer")
    if value > maximum:
        raise AnalysisContractError(f"{name} exceeds maximum")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise AnalysisContractError(f"{name} must be a boolean")
    return value


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
        raise AnalysisContractError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise AnalysisContractError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise AnalysisContractError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_model_authority_and_host_fallbacks(thawed, path=name)
    except AssuranceBaseError as exc:
        raise AnalysisContractError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AnalysisContractError(f"{name} must be a mapping")
    result = _require_structured(dict(value), name)
    return _freeze_structured(result) if frozen else result


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AnalysisContractError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise AnalysisContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise AnalysisContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AnalysisContractError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > maximum:
        raise AnalysisContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise AnalysisContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_symbol_ids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AnalysisContractError(f"{name} must be a list")
    ordered = tuple(sorted(_symbol_id(value, name) for value in values))
    if len(ordered) > MAX_ID_LIST:
        raise AnalysisContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise AnalysisContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_enums(
    values: Iterable[Any],
    enum_type: type[Enum],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AnalysisContractError(f"{name} must be a list")
    ordered = tuple(sorted(_enum(value, enum_type, name) for value in values))
    if len(ordered) > maximum:
        raise AnalysisContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise AnalysisContractError(f"{name} must not contain duplicates")
    return ordered


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except AssuranceBaseError as exc:
            raise AnalysisContractError(str(exc)) from exc
    raise AnalysisContractError(f"{name} must be AssuranceArtifactHeader or mapping")


# ---------------------------------------------------------------------------
# SourceSpan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Bounded source location for minimized survivor and gap reports."""

    path: str
    start_line: int
    end_line: int
    start_col: int | None = None
    end_col: int | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "path",
            "start_line",
            "end_line",
            "start_col",
            "end_col",
            "span_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _repo_path(self.path, "path"))
        start_line = _pos_int(self.start_line, "start_line", maximum=MAX_LINE)
        end_line = _pos_int(self.end_line, "end_line", maximum=MAX_LINE)
        if end_line < start_line:
            raise AnalysisContractError("end_line must be >= start_line")
        object.__setattr__(self, "start_line", start_line)
        object.__setattr__(self, "end_line", end_line)
        start_col = self.start_col
        end_col = self.end_col
        if start_col is not None:
            start_col = _nonneg_int(start_col, "start_col", maximum=MAX_COL)
        if end_col is not None:
            end_col = _nonneg_int(end_col, "end_col", maximum=MAX_COL)
        if start_col is not None and end_col is not None and end_line == start_line:
            if end_col < start_col:
                raise AnalysisContractError(
                    "end_col must be >= start_col on a single-line span"
                )
        object.__setattr__(self, "start_col", start_col)
        object.__setattr__(self, "end_col", end_col)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SOURCE_SPAN_SCHEMA,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_col": self.start_col,
            "end_col": self.end_col,
        }

    @property
    def span_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["span_cid"] = self.span_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceSpan":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("span_cid")
        if payload.pop("schema") != SOURCE_SPAN_SCHEMA:
            raise AnalysisContractError("unsupported SourceSpan schema version")
        result = cls(
            path=payload["path"],
            start_line=payload["start_line"],
            end_line=payload["end_line"],
            start_col=payload["start_col"],
            end_col=payload["end_col"],
        )
        if claimed != result.span_cid:
            raise AnalysisContractError("SourceSpan span_cid identity mismatch")
        return result


def _normalize_source_span(
    value: SourceSpan | Mapping[str, Any],
    name: str = "source_span",
) -> SourceSpan:
    if isinstance(value, SourceSpan):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "span_cid" in value:
            return SourceSpan.from_dict(value)
        return SourceSpan(
            path=value["path"],
            start_line=value["start_line"],
            end_line=value["end_line"],
            start_col=value.get("start_col"),
            end_col=value.get("end_col"),
        )
    raise AnalysisContractError(f"{name} must be SourceSpan or mapping")


def _normalize_source_spans(
    values: Sequence[SourceSpan | Mapping[str, Any]],
    name: str = "source_spans",
) -> tuple[SourceSpan, ...]:
    if not isinstance(values, (list, tuple)):
        raise AnalysisContractError(f"{name} must be a list")
    if len(values) > MAX_SPANS:
        raise AnalysisContractError(f"{name} exceeds maximum length")
    spans = tuple(
        _normalize_source_span(item, f"{name}[{index}]")
        for index, item in enumerate(values)
    )
    # Stable order by path, then start_line, then span_cid.
    return tuple(
        sorted(
            spans,
            key=lambda item: (item.path, item.start_line, item.end_line, item.span_cid),
        )
    )


# ---------------------------------------------------------------------------
# MinimizedEvidenceBinding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MinimizedEvidenceBinding:
    """Bounded evidence references for survivor and gap reports.

    Binds only minimized evidence CIDs and identities — full execution logs are
    excluded from model context unless minimization fails explicitly.
    """

    evidence_cids: Sequence[str]
    minimized: bool = True
    minimization_failed: bool = False
    reproduction_input_cid: str | None = None
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "evidence_cids",
            "minimized",
            "minimization_failed",
            "reproduction_input_cid",
            "notes",
            "binding_cid",
        }
    )

    def __post_init__(self) -> None:
        evidence = _unique_sorted_cids(list(self.evidence_cids), "evidence_cids")
        object.__setattr__(self, "evidence_cids", evidence)
        minimized = _bool(self.minimized, "minimized")
        failed = _bool(self.minimization_failed, "minimization_failed")
        if minimized and failed:
            raise AnalysisContractError(
                "minimized evidence cannot also claim minimization_failed"
            )
        if not minimized and not failed:
            raise AnalysisContractError(
                "non-minimized evidence requires minimization_failed=true"
            )
        if not failed and not evidence:
            raise AnalysisContractError(
                "minimized evidence_cids must not be empty when minimization succeeds"
            )
        object.__setattr__(self, "minimized", minimized)
        object.__setattr__(self, "minimization_failed", failed)
        object.__setattr__(
            self,
            "reproduction_input_cid",
            _optional_cid(self.reproduction_input_cid, "reproduction_input_cid"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MINIMIZED_EVIDENCE_SCHEMA,
            "evidence_cids": list(self.evidence_cids),
            "minimized": self.minimized,
            "minimization_failed": self.minimization_failed,
            "reproduction_input_cid": self.reproduction_input_cid,
            "notes": self.notes,
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["binding_cid"] = self.binding_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MinimizedEvidenceBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("binding_cid")
        if payload.pop("schema") != MINIMIZED_EVIDENCE_SCHEMA:
            raise AnalysisContractError(
                "unsupported MinimizedEvidenceBinding schema version"
            )
        result = cls(
            evidence_cids=payload["evidence_cids"],
            minimized=payload["minimized"],
            minimization_failed=payload["minimization_failed"],
            reproduction_input_cid=payload["reproduction_input_cid"],
            notes=payload["notes"],
        )
        if claimed != result.binding_cid:
            raise AnalysisContractError(
                "MinimizedEvidenceBinding binding_cid identity mismatch"
            )
        return result


def _normalize_minimized_evidence(
    value: MinimizedEvidenceBinding | Mapping[str, Any],
    name: str = "minimized_evidence",
) -> MinimizedEvidenceBinding:
    if isinstance(value, MinimizedEvidenceBinding):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "binding_cid" in value:
            return MinimizedEvidenceBinding.from_dict(value)
        return MinimizedEvidenceBinding(
            evidence_cids=value.get("evidence_cids", ()),
            minimized=value.get("minimized", True),
            minimization_failed=value.get("minimization_failed", False),
            reproduction_input_cid=value.get("reproduction_input_cid"),
            notes=value.get("notes"),
        )
    raise AnalysisContractError(
        f"{name} must be MinimizedEvidenceBinding or mapping"
    )


# ---------------------------------------------------------------------------
# SurvivingMutantReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SurvivingMutantReport:
    """Minimized report for one surviving mutant (plan §9).

    Interface: ``SurvivingMutantReport@1``

    Contains the smallest changed source region, symbol IDs, violated/missing
    property, detectors run and omitted, smallest reproducing input, expected
    and observed behavior, source spans, dependency path, proof/receipt IDs,
    reproduction command, risk, and minimized evidence bindings. Full logs are
    excluded unless minimization fails.
    """

    header: AssuranceArtifactHeader
    report_id: str
    candidate_id: str
    candidate_cid: str
    outcome_cid: str
    risk_class: SurvivorRiskClass | str
    symbol_ids: Sequence[str]
    violated_or_missing_property: str
    detectors_run: Sequence[str]
    detectors_omitted: Sequence[str]
    expected_behavior: str
    observed_behavior: str
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    dependency_path: Sequence[str]
    reproduction_command: str
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    proof_cids: Sequence[str] = ()
    receipt_cids: Sequence[str] = ()
    equivalence_assessment_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "report_id",
            "candidate_id",
            "candidate_cid",
            "outcome_cid",
            "risk_class",
            "symbol_ids",
            "violated_or_missing_property",
            "detectors_run",
            "detectors_omitted",
            "expected_behavior",
            "observed_behavior",
            "source_spans",
            "dependency_path",
            "reproduction_command",
            "minimized_evidence",
            "proof_cids",
            "receipt_cids",
            "equivalence_assessment_cid",
            "notes",
            "metadata",
            "report_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "surviving_mutant_report":
            raise AnalysisContractError(
                "header.artifact_kind must be surviving_mutant_report"
            )
        object.__setattr__(self, "report_id", _token(self.report_id, "report_id"))
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(self, "outcome_cid", _cid(self.outcome_cid, "outcome_cid"))
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, SurvivorRiskClass, "risk_class"),
        )
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        if not symbols:
            raise AnalysisContractError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        object.__setattr__(
            self,
            "violated_or_missing_property",
            _text(self.violated_or_missing_property, "violated_or_missing_property"),
        )
        run = _unique_sorted_tokens(
            list(self.detectors_run), "detectors_run", maximum=MAX_DETECTORS
        )
        omitted = _unique_sorted_tokens(
            list(self.detectors_omitted),
            "detectors_omitted",
            maximum=MAX_DETECTORS,
        )
        overlap = set(run) & set(omitted)
        if overlap:
            raise AnalysisContractError(
                f"detectors_run and detectors_omitted must be disjoint; "
                f"overlap={sorted(overlap)}"
            )
        object.__setattr__(self, "detectors_run", run)
        object.__setattr__(self, "detectors_omitted", omitted)
        object.__setattr__(
            self, "expected_behavior", _text(self.expected_behavior, "expected_behavior")
        )
        object.__setattr__(
            self, "observed_behavior", _text(self.observed_behavior, "observed_behavior")
        )
        spans = _normalize_source_spans(list(self.source_spans), "source_spans")
        if not spans:
            raise AnalysisContractError("source_spans must not be empty")
        object.__setattr__(self, "source_spans", spans)
        path = _unique_sorted_tokens(
            list(self.dependency_path),
            "dependency_path",
            maximum=MAX_DEPENDENCY_PATH,
        )
        if not path:
            raise AnalysisContractError("dependency_path must not be empty")
        object.__setattr__(self, "dependency_path", path)
        object.__setattr__(
            self,
            "reproduction_command",
            _text(
                self.reproduction_command,
                "reproduction_command",
                maximum=MAX_COMMAND_CHARS,
            ),
        )
        evidence = _normalize_minimized_evidence(self.minimized_evidence)
        object.__setattr__(self, "minimized_evidence", evidence)
        object.__setattr__(
            self, "proof_cids", _unique_sorted_cids(list(self.proof_cids), "proof_cids")
        )
        object.__setattr__(
            self,
            "receipt_cids",
            _unique_sorted_cids(list(self.receipt_cids), "receipt_cids"),
        )
        object.__setattr__(
            self,
            "equivalence_assessment_cid",
            _optional_cid(
                self.equivalence_assessment_cid, "equivalence_assessment_cid"
            ),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SURVIVING_MUTANT_REPORT_SCHEMA,
            "interface_id": SURVIVING_MUTANT_REPORT_INTERFACE,
            "header": self.header.identity_payload(),
            "report_id": self.report_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "outcome_cid": self.outcome_cid,
            "risk_class": self.risk_class,
            "symbol_ids": list(self.symbol_ids),
            "violated_or_missing_property": self.violated_or_missing_property,
            "detectors_run": list(self.detectors_run),
            "detectors_omitted": list(self.detectors_omitted),
            "expected_behavior": self.expected_behavior,
            "observed_behavior": self.observed_behavior,
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "reproduction_command": self.reproduction_command,
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "proof_cids": list(self.proof_cids),
            "receipt_cids": list(self.receipt_cids),
            "equivalence_assessment_cid": self.equivalence_assessment_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def report_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SURVIVING_MUTANT_REPORT_SCHEMA,
            "interface_id": SURVIVING_MUTANT_REPORT_INTERFACE,
            "header": self.header.to_dict(),
            "report_id": self.report_id,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "outcome_cid": self.outcome_cid,
            "risk_class": self.risk_class,
            "symbol_ids": list(self.symbol_ids),
            "violated_or_missing_property": self.violated_or_missing_property,
            "detectors_run": list(self.detectors_run),
            "detectors_omitted": list(self.detectors_omitted),
            "expected_behavior": self.expected_behavior,
            "observed_behavior": self.observed_behavior,
            "source_spans": [span.to_dict() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "reproduction_command": self.reproduction_command,
            "minimized_evidence": self.minimized_evidence.to_dict(),
            "proof_cids": list(self.proof_cids),
            "receipt_cids": list(self.receipt_cids),
            "equivalence_assessment_cid": self.equivalence_assessment_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "report_cid": self.report_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SurvivingMutantReport":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("report_cid")
        if payload.pop("schema") != SURVIVING_MUTANT_REPORT_SCHEMA:
            raise AnalysisContractError(
                "unsupported SurvivingMutantReport schema version"
            )
        if payload.pop("interface_id") != SURVIVING_MUTANT_REPORT_INTERFACE:
            raise AnalysisContractError(
                "unsupported SurvivingMutantReport interface_id"
            )
        result = cls(
            header=payload["header"],
            report_id=payload["report_id"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            outcome_cid=payload["outcome_cid"],
            risk_class=payload["risk_class"],
            symbol_ids=payload["symbol_ids"],
            violated_or_missing_property=payload["violated_or_missing_property"],
            detectors_run=payload["detectors_run"],
            detectors_omitted=payload["detectors_omitted"],
            expected_behavior=payload["expected_behavior"],
            observed_behavior=payload["observed_behavior"],
            source_spans=payload["source_spans"],
            dependency_path=payload["dependency_path"],
            reproduction_command=payload["reproduction_command"],
            minimized_evidence=payload["minimized_evidence"],
            proof_cids=payload["proof_cids"],
            receipt_cids=payload["receipt_cids"],
            equivalence_assessment_cid=payload["equivalence_assessment_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.report_cid:
            raise AnalysisContractError(
                "SurvivingMutantReport report_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# AssuranceGap
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssuranceGap:
    """Diagnosed assurance gap for a survivor or vacuous assurance claim.

    Interface: ``AssuranceGap@1``

    Uses the closed plan §5 gap taxonomy. High-risk survivors must always bind
    a gap; ``unknown`` requires human review rather than silent omission.
    """

    header: AssuranceArtifactHeader
    gap_id: str
    gap_class: AssuranceGapClass | str
    severity: GapSeverity | str
    risk_class: SurvivorRiskClass | str
    summary: str
    candidate_id: str | None
    candidate_cid: str | None
    survivor_report_cid: str | None
    violated_or_missing_property: str
    symbol_ids: Sequence[str]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    dependency_path: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    requires_human_review: bool = False
    detection_failure_cids: Sequence[str] = ()
    vacuity_finding_cids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "gap_id",
            "gap_class",
            "severity",
            "risk_class",
            "summary",
            "candidate_id",
            "candidate_cid",
            "survivor_report_cid",
            "violated_or_missing_property",
            "symbol_ids",
            "source_spans",
            "dependency_path",
            "minimized_evidence",
            "requires_human_review",
            "detection_failure_cids",
            "vacuity_finding_cids",
            "notes",
            "metadata",
            "gap_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "assurance_gap":
            raise AnalysisContractError(
                "header.artifact_kind must be assurance_gap"
            )
        object.__setattr__(self, "gap_id", _token(self.gap_id, "gap_id"))
        gap_class = _enum(self.gap_class, AssuranceGapClass, "gap_class")
        object.__setattr__(self, "gap_class", gap_class)
        object.__setattr__(
            self, "severity", _enum(self.severity, GapSeverity, "severity")
        )
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, SurvivorRiskClass, "risk_class"),
        )
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        candidate_id = self.candidate_id
        if candidate_id is not None:
            candidate_id = _token(candidate_id, "candidate_id")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(
            self, "candidate_cid", _optional_cid(self.candidate_cid, "candidate_cid")
        )
        if (self.candidate_id is None) != (self.candidate_cid is None):
            raise AnalysisContractError(
                "candidate_id and candidate_cid must both be set or both be null"
            )
        object.__setattr__(
            self,
            "survivor_report_cid",
            _optional_cid(self.survivor_report_cid, "survivor_report_cid"),
        )
        object.__setattr__(
            self,
            "violated_or_missing_property",
            _text(self.violated_or_missing_property, "violated_or_missing_property"),
        )
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        if not symbols:
            raise AnalysisContractError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        spans = _normalize_source_spans(list(self.source_spans), "source_spans")
        if not spans:
            raise AnalysisContractError("source_spans must not be empty")
        object.__setattr__(self, "source_spans", spans)
        path = _unique_sorted_tokens(
            list(self.dependency_path),
            "dependency_path",
            maximum=MAX_DEPENDENCY_PATH,
        )
        if not path:
            raise AnalysisContractError("dependency_path must not be empty")
        object.__setattr__(self, "dependency_path", path)
        evidence = _normalize_minimized_evidence(self.minimized_evidence)
        object.__setattr__(self, "minimized_evidence", evidence)
        requires_review = _bool(self.requires_human_review, "requires_human_review")
        if gap_class == AssuranceGapClass.UNKNOWN.value and not requires_review:
            raise AnalysisContractError(
                "gap_class unknown requires requires_human_review=true"
            )
        object.__setattr__(self, "requires_human_review", requires_review)
        object.__setattr__(
            self,
            "detection_failure_cids",
            _unique_sorted_cids(
                list(self.detection_failure_cids), "detection_failure_cids"
            ),
        )
        object.__setattr__(
            self,
            "vacuity_finding_cids",
            _unique_sorted_cids(
                list(self.vacuity_finding_cids), "vacuity_finding_cids"
            ),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_GAP_SCHEMA,
            "interface_id": ASSURANCE_GAP_INTERFACE,
            "header": self.header.identity_payload(),
            "gap_id": self.gap_id,
            "gap_class": self.gap_class,
            "severity": self.severity,
            "risk_class": self.risk_class,
            "summary": self.summary,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "survivor_report_cid": self.survivor_report_cid,
            "violated_or_missing_property": self.violated_or_missing_property,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "requires_human_review": self.requires_human_review,
            "detection_failure_cids": list(self.detection_failure_cids),
            "vacuity_finding_cids": list(self.vacuity_finding_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def gap_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_GAP_SCHEMA,
            "interface_id": ASSURANCE_GAP_INTERFACE,
            "header": self.header.to_dict(),
            "gap_id": self.gap_id,
            "gap_class": self.gap_class,
            "severity": self.severity,
            "risk_class": self.risk_class,
            "summary": self.summary,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "survivor_report_cid": self.survivor_report_cid,
            "violated_or_missing_property": self.violated_or_missing_property,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.to_dict() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.to_dict(),
            "requires_human_review": self.requires_human_review,
            "detection_failure_cids": list(self.detection_failure_cids),
            "vacuity_finding_cids": list(self.vacuity_finding_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "gap_cid": self.gap_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AssuranceGap":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("gap_cid")
        if payload.pop("schema") != ASSURANCE_GAP_SCHEMA:
            raise AnalysisContractError("unsupported AssuranceGap schema version")
        if payload.pop("interface_id") != ASSURANCE_GAP_INTERFACE:
            raise AnalysisContractError("unsupported AssuranceGap interface_id")
        result = cls(
            header=payload["header"],
            gap_id=payload["gap_id"],
            gap_class=payload["gap_class"],
            severity=payload["severity"],
            risk_class=payload["risk_class"],
            summary=payload["summary"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            survivor_report_cid=payload["survivor_report_cid"],
            violated_or_missing_property=payload["violated_or_missing_property"],
            symbol_ids=payload["symbol_ids"],
            source_spans=payload["source_spans"],
            dependency_path=payload["dependency_path"],
            minimized_evidence=payload["minimized_evidence"],
            requires_human_review=payload["requires_human_review"],
            detection_failure_cids=payload["detection_failure_cids"],
            vacuity_finding_cids=payload["vacuity_finding_cids"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.gap_cid:
            raise AnalysisContractError("AssuranceGap gap_cid identity mismatch")
        return result


# ---------------------------------------------------------------------------
# VacuityFinding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VacuityFinding:
    """Vacuity diagnosis that states exactly what remains proven.

    Interface: ``VacuityFinding@1``

    Covers formal-proof, policy, test, and ZK/receipt families. ``what_remains_proven``
    is mandatory and must be nonempty — vacuity never silently overclaims.
    """

    header: AssuranceArtifactHeader
    finding_id: str
    vacuity_family: VacuityFamily | str
    vacuity_kind: VacuityKind | str
    subject_id: str
    subject_cid: str | None
    vacuous_claim: str
    what_remains_proven: str
    what_is_not_proven: str
    symbol_ids: Sequence[str]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    dependency_path: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "finding_id",
            "vacuity_family",
            "vacuity_kind",
            "subject_id",
            "subject_cid",
            "vacuous_claim",
            "what_remains_proven",
            "what_is_not_proven",
            "symbol_ids",
            "source_spans",
            "dependency_path",
            "minimized_evidence",
            "notes",
            "metadata",
            "finding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "vacuity_finding":
            raise AnalysisContractError(
                "header.artifact_kind must be vacuity_finding"
            )
        object.__setattr__(
            self, "finding_id", _token(self.finding_id, "finding_id")
        )
        family = _enum(self.vacuity_family, VacuityFamily, "vacuity_family")
        kind = _enum(self.vacuity_kind, VacuityKind, "vacuity_kind")
        allowed = _VACUITY_FAMILY_KINDS[family]
        if kind not in allowed:
            raise AnalysisContractError(
                f"vacuity_kind {kind!r} is not admitted for vacuity_family "
                f"{family!r}; allowed={sorted(allowed)}"
            )
        object.__setattr__(self, "vacuity_family", family)
        object.__setattr__(self, "vacuity_kind", kind)
        object.__setattr__(
            self, "subject_id", _token(self.subject_id, "subject_id")
        )
        object.__setattr__(
            self, "subject_cid", _optional_cid(self.subject_cid, "subject_cid")
        )
        object.__setattr__(
            self, "vacuous_claim", _text(self.vacuous_claim, "vacuous_claim")
        )
        remains = _text(self.what_remains_proven, "what_remains_proven")
        # Fail closed: must state exactly what remains proven (acceptance).
        object.__setattr__(self, "what_remains_proven", remains)
        object.__setattr__(
            self,
            "what_is_not_proven",
            _text(self.what_is_not_proven, "what_is_not_proven"),
        )
        if remains == self.what_is_not_proven:
            raise AnalysisContractError(
                "what_remains_proven must differ from what_is_not_proven"
            )
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        if not symbols:
            raise AnalysisContractError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        spans = _normalize_source_spans(list(self.source_spans), "source_spans")
        if not spans:
            raise AnalysisContractError("source_spans must not be empty")
        object.__setattr__(self, "source_spans", spans)
        path = _unique_sorted_tokens(
            list(self.dependency_path),
            "dependency_path",
            maximum=MAX_DEPENDENCY_PATH,
        )
        if not path:
            raise AnalysisContractError("dependency_path must not be empty")
        object.__setattr__(self, "dependency_path", path)
        evidence = _normalize_minimized_evidence(self.minimized_evidence)
        object.__setattr__(self, "minimized_evidence", evidence)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": VACUITY_FINDING_SCHEMA,
            "interface_id": VACUITY_FINDING_INTERFACE,
            "header": self.header.identity_payload(),
            "finding_id": self.finding_id,
            "vacuity_family": self.vacuity_family,
            "vacuity_kind": self.vacuity_kind,
            "subject_id": self.subject_id,
            "subject_cid": self.subject_cid,
            "vacuous_claim": self.vacuous_claim,
            "what_remains_proven": self.what_remains_proven,
            "what_is_not_proven": self.what_is_not_proven,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def finding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": VACUITY_FINDING_SCHEMA,
            "interface_id": VACUITY_FINDING_INTERFACE,
            "header": self.header.to_dict(),
            "finding_id": self.finding_id,
            "vacuity_family": self.vacuity_family,
            "vacuity_kind": self.vacuity_kind,
            "subject_id": self.subject_id,
            "subject_cid": self.subject_cid,
            "vacuous_claim": self.vacuous_claim,
            "what_remains_proven": self.what_remains_proven,
            "what_is_not_proven": self.what_is_not_proven,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.to_dict() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.to_dict(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "finding_cid": self.finding_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VacuityFinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("finding_cid")
        if payload.pop("schema") != VACUITY_FINDING_SCHEMA:
            raise AnalysisContractError(
                "unsupported VacuityFinding schema version"
            )
        if payload.pop("interface_id") != VACUITY_FINDING_INTERFACE:
            raise AnalysisContractError(
                "unsupported VacuityFinding interface_id"
            )
        result = cls(
            header=payload["header"],
            finding_id=payload["finding_id"],
            vacuity_family=payload["vacuity_family"],
            vacuity_kind=payload["vacuity_kind"],
            subject_id=payload["subject_id"],
            subject_cid=payload["subject_cid"],
            vacuous_claim=payload["vacuous_claim"],
            what_remains_proven=payload["what_remains_proven"],
            what_is_not_proven=payload["what_is_not_proven"],
            symbol_ids=payload["symbol_ids"],
            source_spans=payload["source_spans"],
            dependency_path=payload["dependency_path"],
            minimized_evidence=payload["minimized_evidence"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.finding_cid:
            raise AnalysisContractError(
                "VacuityFinding finding_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# DetectionFailure
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectionFailure:
    """Predicted-versus-observed detector failure for one mutant.

    Interface: ``DetectionFailure@1``

    Records selection, execution, observation, path, or assertion-strength
    failures with minimized evidence.
    """

    header: AssuranceArtifactHeader
    failure_id: str
    failure_kind: DetectionFailureKind | str
    candidate_id: str
    candidate_cid: str
    detector_id: str
    predicted: bool
    selected: bool
    executed: bool
    observed: bool
    summary: str
    dependency_path: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    expected_detection_set_cid: str | None = None
    outcome_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "failure_id",
            "failure_kind",
            "candidate_id",
            "candidate_cid",
            "detector_id",
            "predicted",
            "selected",
            "executed",
            "observed",
            "summary",
            "dependency_path",
            "minimized_evidence",
            "expected_detection_set_cid",
            "outcome_cid",
            "notes",
            "metadata",
            "failure_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "detection_failure":
            raise AnalysisContractError(
                "header.artifact_kind must be detection_failure"
            )
        object.__setattr__(
            self, "failure_id", _token(self.failure_id, "failure_id")
        )
        kind = _enum(self.failure_kind, DetectionFailureKind, "failure_kind")
        object.__setattr__(self, "failure_kind", kind)
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self, "candidate_cid", _cid(self.candidate_cid, "candidate_cid")
        )
        object.__setattr__(
            self, "detector_id", _token(self.detector_id, "detector_id")
        )
        predicted = _bool(self.predicted, "predicted")
        selected = _bool(self.selected, "selected")
        executed = _bool(self.executed, "executed")
        observed = _bool(self.observed, "observed")
        # Nesting: observed ⊆ executed ⊆ selected (when selected is claimed).
        if executed and not selected:
            raise AnalysisContractError(
                "executed detectors must also be selected"
            )
        if observed and not executed:
            raise AnalysisContractError(
                "observed detectors must also be executed"
            )
        # Kind-specific role invariants.
        if kind == DetectionFailureKind.SELECTION_MISS.value:
            if not predicted or selected:
                raise AnalysisContractError(
                    "selection_miss requires predicted=true and selected=false"
                )
        if kind == DetectionFailureKind.EXECUTION_MISS.value:
            if not selected or executed:
                raise AnalysisContractError(
                    "execution_miss requires selected=true and executed=false"
                )
        if kind in {
            DetectionFailureKind.OBSERVATION_MISS.value,
            DetectionFailureKind.EXPECTED_NOT_OBSERVED.value,
            DetectionFailureKind.PATH_MISS.value,
            DetectionFailureKind.ASSERTION_STRENGTH_FAILURE.value,
        }:
            if not executed or observed:
                raise AnalysisContractError(
                    f"{kind} requires executed=true and observed=false"
                )
        if kind == DetectionFailureKind.UNEXPECTED_OBSERVED.value:
            if predicted or not observed:
                raise AnalysisContractError(
                    "unexpected_observed requires predicted=false and observed=true"
                )
        object.__setattr__(self, "predicted", predicted)
        object.__setattr__(self, "selected", selected)
        object.__setattr__(self, "executed", executed)
        object.__setattr__(self, "observed", observed)
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        path = _unique_sorted_tokens(
            list(self.dependency_path),
            "dependency_path",
            maximum=MAX_DEPENDENCY_PATH,
        )
        if not path:
            raise AnalysisContractError("dependency_path must not be empty")
        object.__setattr__(self, "dependency_path", path)
        evidence = _normalize_minimized_evidence(self.minimized_evidence)
        object.__setattr__(self, "minimized_evidence", evidence)
        object.__setattr__(
            self,
            "expected_detection_set_cid",
            _optional_cid(
                self.expected_detection_set_cid, "expected_detection_set_cid"
            ),
        )
        object.__setattr__(
            self, "outcome_cid", _optional_cid(self.outcome_cid, "outcome_cid")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DETECTION_FAILURE_SCHEMA,
            "interface_id": DETECTION_FAILURE_INTERFACE,
            "header": self.header.identity_payload(),
            "failure_id": self.failure_id,
            "failure_kind": self.failure_kind,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "detector_id": self.detector_id,
            "predicted": self.predicted,
            "selected": self.selected,
            "executed": self.executed,
            "observed": self.observed,
            "summary": self.summary,
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "expected_detection_set_cid": self.expected_detection_set_cid,
            "outcome_cid": self.outcome_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def failure_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DETECTION_FAILURE_SCHEMA,
            "interface_id": DETECTION_FAILURE_INTERFACE,
            "header": self.header.to_dict(),
            "failure_id": self.failure_id,
            "failure_kind": self.failure_kind,
            "candidate_id": self.candidate_id,
            "candidate_cid": self.candidate_cid,
            "detector_id": self.detector_id,
            "predicted": self.predicted,
            "selected": self.selected,
            "executed": self.executed,
            "observed": self.observed,
            "summary": self.summary,
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.to_dict(),
            "expected_detection_set_cid": self.expected_detection_set_cid,
            "outcome_cid": self.outcome_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "failure_cid": self.failure_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DetectionFailure":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("failure_cid")
        if payload.pop("schema") != DETECTION_FAILURE_SCHEMA:
            raise AnalysisContractError(
                "unsupported DetectionFailure schema version"
            )
        if payload.pop("interface_id") != DETECTION_FAILURE_INTERFACE:
            raise AnalysisContractError(
                "unsupported DetectionFailure interface_id"
            )
        result = cls(
            header=payload["header"],
            failure_id=payload["failure_id"],
            failure_kind=payload["failure_kind"],
            candidate_id=payload["candidate_id"],
            candidate_cid=payload["candidate_cid"],
            detector_id=payload["detector_id"],
            predicted=payload["predicted"],
            selected=payload["selected"],
            executed=payload["executed"],
            observed=payload["observed"],
            summary=payload["summary"],
            dependency_path=payload["dependency_path"],
            minimized_evidence=payload["minimized_evidence"],
            expected_detection_set_cid=payload["expected_detection_set_cid"],
            outcome_cid=payload["outcome_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.failure_cid:
            raise AnalysisContractError(
                "DetectionFailure failure_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Adequacy profiles
# ---------------------------------------------------------------------------


def _normalize_adequacy_gap_list(
    values: Sequence[Any],
    enum_type: type[Enum],
    name: str,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AnalysisContractError(f"{name} must be a list")
    if len(values) > MAX_GAPS:
        raise AnalysisContractError(f"{name} exceeds maximum length")
    if not values:
        raise AnalysisContractError(f"{name} must not be empty")
    ordered = _unique_sorted_enums(
        list(values), enum_type, name, maximum=MAX_GAPS
    )
    # "none" is exclusive: if present it must be the sole entry.
    none_value = "none"
    if none_value in ordered and len(ordered) > 1:
        raise AnalysisContractError(
            f"{name} cannot combine 'none' with other gap classes"
        )
    return ordered


def _validate_adequacy_verdict_consistency(
    verdict: str,
    gap_classes: Sequence[str],
    name: str = "verdict",
) -> None:
    only_none = list(gap_classes) == ["none"]
    if verdict == AdequacyVerdict.ADEQUATE.value and not only_none:
        raise AnalysisContractError(
            f"{name} adequate requires gap_classes to be exactly ['none']"
        )
    if verdict == AdequacyVerdict.INADEQUATE.value and only_none:
        raise AnalysisContractError(
            f"{name} inadequate requires at least one non-none gap class"
        )
    if verdict == AdequacyVerdict.PARTIAL.value and only_none:
        raise AnalysisContractError(
            f"{name} partial requires at least one non-none gap class"
        )


@dataclass(frozen=True, slots=True)
class TestAdequacyProfile:
    """Closed test-surface adequacy profile.

    Interface: ``TestAdequacyProfile@1``
    """

    header: AssuranceArtifactHeader
    profile_id: str
    target_symbol_ids: Sequence[str]
    verdict: AdequacyVerdict | str
    gap_classes: Sequence[TestAdequacyGapClass | str]
    covered_detector_ids: Sequence[str]
    missing_detector_ids: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "profile_id",
            "target_symbol_ids",
            "verdict",
            "gap_classes",
            "covered_detector_ids",
            "missing_detector_ids",
            "minimized_evidence",
            "notes",
            "metadata",
            "profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "test_adequacy_profile":
            raise AnalysisContractError(
                "header.artifact_kind must be test_adequacy_profile"
            )
        object.__setattr__(
            self, "profile_id", _token(self.profile_id, "profile_id")
        )
        targets = _unique_sorted_symbol_ids(
            list(self.target_symbol_ids), "target_symbol_ids"
        )
        if not targets:
            raise AnalysisContractError("target_symbol_ids must not be empty")
        object.__setattr__(self, "target_symbol_ids", targets)
        verdict = _enum(self.verdict, AdequacyVerdict, "verdict")
        object.__setattr__(self, "verdict", verdict)
        gaps = _normalize_adequacy_gap_list(
            list(self.gap_classes), TestAdequacyGapClass, "gap_classes"
        )
        _validate_adequacy_verdict_consistency(verdict, gaps)
        object.__setattr__(self, "gap_classes", gaps)
        covered = _unique_sorted_tokens(
            list(self.covered_detector_ids),
            "covered_detector_ids",
            maximum=MAX_DETECTORS,
        )
        missing = _unique_sorted_tokens(
            list(self.missing_detector_ids),
            "missing_detector_ids",
            maximum=MAX_DETECTORS,
        )
        overlap = set(covered) & set(missing)
        if overlap:
            raise AnalysisContractError(
                f"covered_detector_ids and missing_detector_ids must be disjoint; "
                f"overlap={sorted(overlap)}"
            )
        object.__setattr__(self, "covered_detector_ids", covered)
        object.__setattr__(self, "missing_detector_ids", missing)
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_minimized_evidence(self.minimized_evidence),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TEST_ADEQUACY_PROFILE_SCHEMA,
            "interface_id": TEST_ADEQUACY_PROFILE_INTERFACE,
            "header": self.header.identity_payload(),
            "profile_id": self.profile_id,
            "target_symbol_ids": list(self.target_symbol_ids),
            "verdict": self.verdict,
            "gap_classes": list(self.gap_classes),
            "covered_detector_ids": list(self.covered_detector_ids),
            "missing_detector_ids": list(self.missing_detector_ids),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TEST_ADEQUACY_PROFILE_SCHEMA,
            "interface_id": TEST_ADEQUACY_PROFILE_INTERFACE,
            "header": self.header.to_dict(),
            "profile_id": self.profile_id,
            "target_symbol_ids": list(self.target_symbol_ids),
            "verdict": self.verdict,
            "gap_classes": list(self.gap_classes),
            "covered_detector_ids": list(self.covered_detector_ids),
            "missing_detector_ids": list(self.missing_detector_ids),
            "minimized_evidence": self.minimized_evidence.to_dict(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "profile_cid": self.profile_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestAdequacyProfile":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("profile_cid")
        if payload.pop("schema") != TEST_ADEQUACY_PROFILE_SCHEMA:
            raise AnalysisContractError(
                "unsupported TestAdequacyProfile schema version"
            )
        if payload.pop("interface_id") != TEST_ADEQUACY_PROFILE_INTERFACE:
            raise AnalysisContractError(
                "unsupported TestAdequacyProfile interface_id"
            )
        result = cls(
            header=payload["header"],
            profile_id=payload["profile_id"],
            target_symbol_ids=payload["target_symbol_ids"],
            verdict=payload["verdict"],
            gap_classes=payload["gap_classes"],
            covered_detector_ids=payload["covered_detector_ids"],
            missing_detector_ids=payload["missing_detector_ids"],
            minimized_evidence=payload["minimized_evidence"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.profile_cid:
            raise AnalysisContractError(
                "TestAdequacyProfile profile_cid identity mismatch"
            )
        return result


@dataclass(frozen=True, slots=True)
class ProofAdequacyProfile:
    """Closed proof-surface adequacy profile.

    Interface: ``ProofAdequacyProfile@1``
    """

    header: AssuranceArtifactHeader
    profile_id: str
    target_symbol_ids: Sequence[str]
    verdict: AdequacyVerdict | str
    gap_classes: Sequence[ProofAdequacyGapClass | str]
    proof_unit_cids: Sequence[str]
    missing_obligation_ids: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "profile_id",
            "target_symbol_ids",
            "verdict",
            "gap_classes",
            "proof_unit_cids",
            "missing_obligation_ids",
            "minimized_evidence",
            "notes",
            "metadata",
            "profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "proof_adequacy_profile":
            raise AnalysisContractError(
                "header.artifact_kind must be proof_adequacy_profile"
            )
        object.__setattr__(
            self, "profile_id", _token(self.profile_id, "profile_id")
        )
        targets = _unique_sorted_symbol_ids(
            list(self.target_symbol_ids), "target_symbol_ids"
        )
        if not targets:
            raise AnalysisContractError("target_symbol_ids must not be empty")
        object.__setattr__(self, "target_symbol_ids", targets)
        verdict = _enum(self.verdict, AdequacyVerdict, "verdict")
        object.__setattr__(self, "verdict", verdict)
        gaps = _normalize_adequacy_gap_list(
            list(self.gap_classes), ProofAdequacyGapClass, "gap_classes"
        )
        _validate_adequacy_verdict_consistency(verdict, gaps)
        object.__setattr__(self, "gap_classes", gaps)
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
                maximum=MAX_ID_LIST,
            ),
        )
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_minimized_evidence(self.minimized_evidence),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PROOF_ADEQUACY_PROFILE_SCHEMA,
            "interface_id": PROOF_ADEQUACY_PROFILE_INTERFACE,
            "header": self.header.identity_payload(),
            "profile_id": self.profile_id,
            "target_symbol_ids": list(self.target_symbol_ids),
            "verdict": self.verdict,
            "gap_classes": list(self.gap_classes),
            "proof_unit_cids": list(self.proof_unit_cids),
            "missing_obligation_ids": list(self.missing_obligation_ids),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PROOF_ADEQUACY_PROFILE_SCHEMA,
            "interface_id": PROOF_ADEQUACY_PROFILE_INTERFACE,
            "header": self.header.to_dict(),
            "profile_id": self.profile_id,
            "target_symbol_ids": list(self.target_symbol_ids),
            "verdict": self.verdict,
            "gap_classes": list(self.gap_classes),
            "proof_unit_cids": list(self.proof_unit_cids),
            "missing_obligation_ids": list(self.missing_obligation_ids),
            "minimized_evidence": self.minimized_evidence.to_dict(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "profile_cid": self.profile_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProofAdequacyProfile":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("profile_cid")
        if payload.pop("schema") != PROOF_ADEQUACY_PROFILE_SCHEMA:
            raise AnalysisContractError(
                "unsupported ProofAdequacyProfile schema version"
            )
        if payload.pop("interface_id") != PROOF_ADEQUACY_PROFILE_INTERFACE:
            raise AnalysisContractError(
                "unsupported ProofAdequacyProfile interface_id"
            )
        result = cls(
            header=payload["header"],
            profile_id=payload["profile_id"],
            target_symbol_ids=payload["target_symbol_ids"],
            verdict=payload["verdict"],
            gap_classes=payload["gap_classes"],
            proof_unit_cids=payload["proof_unit_cids"],
            missing_obligation_ids=payload["missing_obligation_ids"],
            minimized_evidence=payload["minimized_evidence"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.profile_cid:
            raise AnalysisContractError(
                "ProofAdequacyProfile profile_cid identity mismatch"
            )
        return result


@dataclass(frozen=True, slots=True)
class PolicyAdequacyProfile:
    """Closed policy-surface adequacy profile.

    Interface: ``PolicyAdequacyProfile@1``
    """

    header: AssuranceArtifactHeader
    profile_id: str
    target_symbol_ids: Sequence[str]
    verdict: AdequacyVerdict | str
    gap_classes: Sequence[PolicyAdequacyGapClass | str]
    policy_cids: Sequence[str]
    missing_constraint_ids: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "profile_id",
            "target_symbol_ids",
            "verdict",
            "gap_classes",
            "policy_cids",
            "missing_constraint_ids",
            "minimized_evidence",
            "notes",
            "metadata",
            "profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "policy_adequacy_profile":
            raise AnalysisContractError(
                "header.artifact_kind must be policy_adequacy_profile"
            )
        object.__setattr__(
            self, "profile_id", _token(self.profile_id, "profile_id")
        )
        targets = _unique_sorted_symbol_ids(
            list(self.target_symbol_ids), "target_symbol_ids"
        )
        if not targets:
            raise AnalysisContractError("target_symbol_ids must not be empty")
        object.__setattr__(self, "target_symbol_ids", targets)
        verdict = _enum(self.verdict, AdequacyVerdict, "verdict")
        object.__setattr__(self, "verdict", verdict)
        gaps = _normalize_adequacy_gap_list(
            list(self.gap_classes), PolicyAdequacyGapClass, "gap_classes"
        )
        _validate_adequacy_verdict_consistency(verdict, gaps)
        object.__setattr__(self, "gap_classes", gaps)
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
                maximum=MAX_ID_LIST,
            ),
        )
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_minimized_evidence(self.minimized_evidence),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": POLICY_ADEQUACY_PROFILE_SCHEMA,
            "interface_id": POLICY_ADEQUACY_PROFILE_INTERFACE,
            "header": self.header.identity_payload(),
            "profile_id": self.profile_id,
            "target_symbol_ids": list(self.target_symbol_ids),
            "verdict": self.verdict,
            "gap_classes": list(self.gap_classes),
            "policy_cids": list(self.policy_cids),
            "missing_constraint_ids": list(self.missing_constraint_ids),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": POLICY_ADEQUACY_PROFILE_SCHEMA,
            "interface_id": POLICY_ADEQUACY_PROFILE_INTERFACE,
            "header": self.header.to_dict(),
            "profile_id": self.profile_id,
            "target_symbol_ids": list(self.target_symbol_ids),
            "verdict": self.verdict,
            "gap_classes": list(self.gap_classes),
            "policy_cids": list(self.policy_cids),
            "missing_constraint_ids": list(self.missing_constraint_ids),
            "minimized_evidence": self.minimized_evidence.to_dict(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "profile_cid": self.profile_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PolicyAdequacyProfile":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("profile_cid")
        if payload.pop("schema") != POLICY_ADEQUACY_PROFILE_SCHEMA:
            raise AnalysisContractError(
                "unsupported PolicyAdequacyProfile schema version"
            )
        if payload.pop("interface_id") != POLICY_ADEQUACY_PROFILE_INTERFACE:
            raise AnalysisContractError(
                "unsupported PolicyAdequacyProfile interface_id"
            )
        result = cls(
            header=payload["header"],
            profile_id=payload["profile_id"],
            target_symbol_ids=payload["target_symbol_ids"],
            verdict=payload["verdict"],
            gap_classes=payload["gap_classes"],
            policy_cids=payload["policy_cids"],
            missing_constraint_ids=payload["missing_constraint_ids"],
            minimized_evidence=payload["minimized_evidence"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.profile_cid:
            raise AnalysisContractError(
                "PolicyAdequacyProfile profile_cid identity mismatch"
            )
        return result


@dataclass(frozen=True, slots=True)
class CapsuleAdequacyProfile:
    """Closed semantic-capsule adequacy profile.

    Interface: ``CapsuleAdequacyProfile@1``
    """

    header: AssuranceArtifactHeader
    profile_id: str
    target_symbol_ids: Sequence[str]
    verdict: AdequacyVerdict | str
    gap_classes: Sequence[CapsuleAdequacyGapClass | str]
    capsule_cids: Sequence[str]
    omitted_edge_ids: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "profile_id",
            "target_symbol_ids",
            "verdict",
            "gap_classes",
            "capsule_cids",
            "omitted_edge_ids",
            "minimized_evidence",
            "notes",
            "metadata",
            "profile_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "capsule_adequacy_profile":
            raise AnalysisContractError(
                "header.artifact_kind must be capsule_adequacy_profile"
            )
        object.__setattr__(
            self, "profile_id", _token(self.profile_id, "profile_id")
        )
        targets = _unique_sorted_symbol_ids(
            list(self.target_symbol_ids), "target_symbol_ids"
        )
        if not targets:
            raise AnalysisContractError("target_symbol_ids must not be empty")
        object.__setattr__(self, "target_symbol_ids", targets)
        verdict = _enum(self.verdict, AdequacyVerdict, "verdict")
        object.__setattr__(self, "verdict", verdict)
        gaps = _normalize_adequacy_gap_list(
            list(self.gap_classes), CapsuleAdequacyGapClass, "gap_classes"
        )
        _validate_adequacy_verdict_consistency(verdict, gaps)
        object.__setattr__(self, "gap_classes", gaps)
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
                maximum=MAX_ID_LIST,
            ),
        )
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_minimized_evidence(self.minimized_evidence),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CAPSULE_ADEQUACY_PROFILE_SCHEMA,
            "interface_id": CAPSULE_ADEQUACY_PROFILE_INTERFACE,
            "header": self.header.identity_payload(),
            "profile_id": self.profile_id,
            "target_symbol_ids": list(self.target_symbol_ids),
            "verdict": self.verdict,
            "gap_classes": list(self.gap_classes),
            "capsule_cids": list(self.capsule_cids),
            "omitted_edge_ids": list(self.omitted_edge_ids),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CAPSULE_ADEQUACY_PROFILE_SCHEMA,
            "interface_id": CAPSULE_ADEQUACY_PROFILE_INTERFACE,
            "header": self.header.to_dict(),
            "profile_id": self.profile_id,
            "target_symbol_ids": list(self.target_symbol_ids),
            "verdict": self.verdict,
            "gap_classes": list(self.gap_classes),
            "capsule_cids": list(self.capsule_cids),
            "omitted_edge_ids": list(self.omitted_edge_ids),
            "minimized_evidence": self.minimized_evidence.to_dict(),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "profile_cid": self.profile_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CapsuleAdequacyProfile":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("profile_cid")
        if payload.pop("schema") != CAPSULE_ADEQUACY_PROFILE_SCHEMA:
            raise AnalysisContractError(
                "unsupported CapsuleAdequacyProfile schema version"
            )
        if payload.pop("interface_id") != CAPSULE_ADEQUACY_PROFILE_INTERFACE:
            raise AnalysisContractError(
                "unsupported CapsuleAdequacyProfile interface_id"
            )
        result = cls(
            header=payload["header"],
            profile_id=payload["profile_id"],
            target_symbol_ids=payload["target_symbol_ids"],
            verdict=payload["verdict"],
            gap_classes=payload["gap_classes"],
            capsule_cids=payload["capsule_cids"],
            omitted_edge_ids=payload["omitted_edge_ids"],
            minimized_evidence=payload["minimized_evidence"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.profile_cid:
            raise AnalysisContractError(
                "CapsuleAdequacyProfile profile_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Vocabulary helpers and identity verification
# ---------------------------------------------------------------------------


def assurance_gap_classes() -> tuple[str, ...]:
    """Return the closed assurance-gap taxonomy in declaration order."""

    return tuple(item.value for item in AssuranceGapClass)


def gap_severities() -> tuple[str, ...]:
    """Return the closed gap-severity vocabulary in declaration order."""

    return tuple(item.value for item in GapSeverity)


def survivor_risk_classes() -> tuple[str, ...]:
    """Return the closed survivor risk-class vocabulary in declaration order."""

    return tuple(item.value for item in SurvivorRiskClass)


def vacuity_families() -> tuple[str, ...]:
    """Return the closed vacuity-family vocabulary in declaration order."""

    return tuple(item.value for item in VacuityFamily)


def vacuity_kinds() -> tuple[str, ...]:
    """Return the closed vacuity-kind vocabulary in declaration order."""

    return tuple(item.value for item in VacuityKind)


def vacuity_kinds_for_family(family: VacuityFamily | str) -> tuple[str, ...]:
    """Return admitted vacuity kinds for one family, sorted."""

    normalized = _enum(family, VacuityFamily, "vacuity_family")
    return tuple(sorted(_VACUITY_FAMILY_KINDS[normalized]))


def detection_failure_kinds() -> tuple[str, ...]:
    """Return the closed detection-failure vocabulary in declaration order."""

    return tuple(item.value for item in DetectionFailureKind)


def adequacy_verdicts() -> tuple[str, ...]:
    """Return the closed adequacy-verdict vocabulary in declaration order."""

    return tuple(item.value for item in AdequacyVerdict)


def test_adequacy_gap_classes() -> tuple[str, ...]:
    """Return the closed test-adequacy gap taxonomy in declaration order."""

    return tuple(item.value for item in TestAdequacyGapClass)


def proof_adequacy_gap_classes() -> tuple[str, ...]:
    """Return the closed proof-adequacy gap taxonomy in declaration order."""

    return tuple(item.value for item in ProofAdequacyGapClass)


def policy_adequacy_gap_classes() -> tuple[str, ...]:
    """Return the closed policy-adequacy gap taxonomy in declaration order."""

    return tuple(item.value for item in PolicyAdequacyGapClass)


def capsule_adequacy_gap_classes() -> tuple[str, ...]:
    """Return the closed capsule-adequacy gap taxonomy in declaration order."""

    return tuple(item.value for item in CapsuleAdequacyGapClass)


def verify_survivor_report_identity(
    report: SurvivingMutantReport | Mapping[str, Any],
) -> str:
    """Recompute and return the survivor-report CID; raise on forged input."""

    if isinstance(report, SurvivingMutantReport):
        sealed = report
    elif isinstance(report, Mapping):
        sealed = SurvivingMutantReport.from_dict(report)
    else:
        raise AnalysisContractError(
            "report must be SurvivingMutantReport or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.report_cid:
        raise AnalysisContractError(
            "report_cid identity mismatch with recomputed identity"
        )
    if not sealed.minimized_evidence.minimized and not (
        sealed.minimized_evidence.minimization_failed
    ):
        raise AnalysisContractError(
            "survivor report must bind minimized evidence or explicit failure"
        )
    return recomputed


def verify_gap_identity(gap: AssuranceGap | Mapping[str, Any]) -> str:
    """Recompute and return the gap CID; raise on forged input."""

    if isinstance(gap, AssuranceGap):
        sealed = gap
    elif isinstance(gap, Mapping):
        sealed = AssuranceGap.from_dict(gap)
    else:
        raise AnalysisContractError("gap must be AssuranceGap or mapping")
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.gap_cid:
        raise AnalysisContractError(
            "gap_cid identity mismatch with recomputed identity"
        )
    return recomputed


def verify_vacuity_finding_identity(
    finding: VacuityFinding | Mapping[str, Any],
) -> str:
    """Recompute and return the finding CID; require what_remains_proven."""

    if isinstance(finding, VacuityFinding):
        sealed = finding
    elif isinstance(finding, Mapping):
        sealed = VacuityFinding.from_dict(finding)
    else:
        raise AnalysisContractError(
            "finding must be VacuityFinding or mapping"
        )
    if not sealed.what_remains_proven:
        raise AnalysisContractError(
            "vacuity finding must state exactly what remains proven"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.finding_cid:
        raise AnalysisContractError(
            "finding_cid identity mismatch with recomputed identity"
        )
    return recomputed


def verify_detection_failure_identity(
    failure: DetectionFailure | Mapping[str, Any],
) -> str:
    """Recompute and return the detection-failure CID; raise on forged input."""

    if isinstance(failure, DetectionFailure):
        sealed = failure
    elif isinstance(failure, Mapping):
        sealed = DetectionFailure.from_dict(failure)
    else:
        raise AnalysisContractError(
            "failure must be DetectionFailure or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.failure_cid:
        raise AnalysisContractError(
            "failure_cid identity mismatch with recomputed identity"
        )
    return recomputed


__all__ = [
    "ASSURANCE_GAP_INTERFACE",
    "ASSURANCE_GAP_SCHEMA",
    "CAPSULE_ADEQUACY_PROFILE_INTERFACE",
    "CAPSULE_ADEQUACY_PROFILE_SCHEMA",
    "DETECTION_FAILURE_INTERFACE",
    "DETECTION_FAILURE_SCHEMA",
    "MINIMIZED_EVIDENCE_SCHEMA",
    "POLICY_ADEQUACY_PROFILE_INTERFACE",
    "POLICY_ADEQUACY_PROFILE_SCHEMA",
    "PROOF_ADEQUACY_PROFILE_INTERFACE",
    "PROOF_ADEQUACY_PROFILE_SCHEMA",
    "SOURCE_SPAN_SCHEMA",
    "SURVIVING_MUTANT_REPORT_INTERFACE",
    "SURVIVING_MUTANT_REPORT_SCHEMA",
    "TEST_ADEQUACY_PROFILE_INTERFACE",
    "TEST_ADEQUACY_PROFILE_SCHEMA",
    "VACUITY_FINDING_INTERFACE",
    "VACUITY_FINDING_SCHEMA",
    "AdequacyVerdict",
    "AnalysisContractError",
    "AssuranceGap",
    "AssuranceGapClass",
    "CapsuleAdequacyGapClass",
    "CapsuleAdequacyProfile",
    "DetectionFailure",
    "DetectionFailureKind",
    "GapSeverity",
    "MinimizedEvidenceBinding",
    "PolicyAdequacyGapClass",
    "PolicyAdequacyProfile",
    "ProofAdequacyGapClass",
    "ProofAdequacyProfile",
    "SourceSpan",
    "SurvivingMutantReport",
    "SurvivorRiskClass",
    "TestAdequacyGapClass",
    "TestAdequacyProfile",
    "VacuityFamily",
    "VacuityFinding",
    "VacuityKind",
    "adequacy_verdicts",
    "assurance_gap_classes",
    "capsule_adequacy_gap_classes",
    "detection_failure_kinds",
    "gap_severities",
    "policy_adequacy_gap_classes",
    "proof_adequacy_gap_classes",
    "survivor_risk_classes",
    "test_adequacy_gap_classes",
    "vacuity_families",
    "vacuity_kinds",
    "vacuity_kinds_for_family",
    "verify_detection_failure_identity",
    "verify_gap_identity",
    "verify_survivor_report_identity",
    "verify_vacuity_finding_identity",
]
