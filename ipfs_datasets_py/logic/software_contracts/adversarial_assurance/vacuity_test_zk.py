"""Test, ZK, receipt, and seal vacuity analysis (AAE-027).

Implements the two vacuity-family analyzers required by plan §9 and AAE-G040:

* ``analyze_test_vacuity@1`` — tautologies, type-only / non-null assertions,
  behavior-independent mocks, uncalled targets, permanent skips, path-bypassing
  fixtures, and success declared before effect observation.
* ``analyze_zk_receipt_vacuity@1`` — unbound required fields / source roots /
  environments, inclusion without required-set completeness, caller-selected
  verification keys, signed aggregation presented as direct execution, and
  changed units omitted from delta seals.

Every emitted :class:`VacuityFinding` states exactly what remains proven and
what is not proven (precise nonclaims). Unknown kinds, missing observation
capability, and malformed subjects fail closed.
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
    GeneratorIdentity,
    VersionBinding,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.analysis_contracts import (
    AnalysisContractError,
    MinimizedEvidenceBinding,
    SourceSpan,
    VacuityFamily,
    VacuityFinding,
    VacuityKind,
    verify_vacuity_finding_identity,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

ANALYZE_TEST_VACUITY_INTERFACE: Final[str] = "analyze_test_vacuity@1"
ANALYZE_ZK_RECEIPT_VACUITY_INTERFACE: Final[str] = "analyze_zk_receipt_vacuity@1"

TEST_VACUITY_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-test-vacuity-subject@1"
)
ZK_RECEIPT_VACUITY_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-zk-receipt-vacuity-subject@1"
)
VACUITY_ANALYSIS_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-vacuity-analysis-result@1"
)
VACUITY_ANALYSIS_RESULT_INTERFACE: Final[str] = "VacuityAnalysisResult@1"

GENERATOR_ID: Final[str] = "vacuity_test_zk"
GENERATOR_VERSION: Final[str] = "1.0.0"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_LIST: Final[int] = 1_024
MAX_ASSERTIONS: Final[int] = 256
MAX_MOCKS: Final[int] = 256
MAX_UNITS: Final[int] = 4_096
MAX_NONCLAIMS: Final[int] = 256
MAX_FINDINGS: Final[int] = 256

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)

# Assertion expression kinds admitted on test subjects (closed).
_TAUTOLOGY_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "true",
        "True",
        "TRUE",
        "1",
        "⊤",
        "tautology",
        "always_true",
        "assert_true",
        "pass",
    }
)


class VacuityTestZkError(AssuranceBaseError):
    """Raised when test/ZK vacuity analysis inputs fail closed."""


class TestAssertionStrength(str, Enum):
    """Closed assertion-strength vocabulary for test vacuity subjects."""

    TAUTOLOGY = "tautology"
    TYPE_ONLY = "type_only"
    NON_NULL_ONLY = "non_null_only"
    BEHAVIORAL = "behavioral"
    EFFECT_OBSERVING = "effect_observing"


class VerificationKeySource(str, Enum):
    """Who selects the verification key bound into a ZK/receipt subject."""

    AUTHORITY = "authority"
    CALLER = "caller"
    UNBOUND = "unbound"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise VacuityTestZkError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise VacuityTestZkError(
            f"{name} must be NFC-normalized and free of leading/trailing whitespace"
        )
    if len(value) > maximum:
        raise VacuityTestZkError(f"{name} exceeds maximum length")
    reject_private_model_authority_and_host_fallbacks({name: value}, path=name)
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise VacuityTestZkError(f"{name} must be a boolean")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise VacuityTestZkError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise VacuityTestZkError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    text = _text(value, name)
    try:
        validate_cid(text)
    except Exception as exc:  # pragma: no cover - validate_cid raises ValueError
        raise VacuityTestZkError(f"{name} must be a valid CIDv1") from exc
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
            raise VacuityTestZkError(
                f"{name}={value!r} is not an admitted {enum_type.__name__}"
            ) from exc
    raise VacuityTestZkError(f"{name} must be {enum_type.__name__} or string")


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
        raise VacuityTestZkError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        raise VacuityTestZkError(
            f"{name} field set mismatch; missing={missing}; extra={extra}"
        )
    return dict(data)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VacuityTestZkError(f"{name} must be a mapping")
    reject_private_model_authority_and_host_fallbacks(value, path=name)
    validate_structured_value(value)
    return MappingProxyType(_thaw_structured(value))


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_LIST,
    symbol: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise VacuityTestZkError(f"{name} must be a list")
    if len(values) > maximum:
        raise VacuityTestZkError(f"{name} exceeds maximum length")
    seen: set[str] = set()
    out: list[str] = []
    for index, raw in enumerate(values):
        item = _symbol_id(raw, f"{name}[{index}]") if symbol else _token(raw, f"{name}[{index}]")
        if item in seen:
            raise VacuityTestZkError(f"{name} must not contain duplicates")
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
        raise VacuityTestZkError(f"{name} must be a list")
    if len(values) > maximum:
        raise VacuityTestZkError(f"{name} exceeds maximum length")
    seen: set[str] = set()
    out: list[str] = []
    for index, raw in enumerate(values):
        item = _text(raw, f"{name}[{index}]")
        if item in seen:
            raise VacuityTestZkError(f"{name} must not contain duplicates")
        seen.add(item)
        out.append(item)
    return tuple(sorted(out))


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
                raise VacuityTestZkError(str(exc)) from exc
        try:
            return SourceSpan(
                path=value["path"],
                start_line=value["start_line"],
                end_line=value["end_line"],
                start_col=value.get("start_col"),
                end_col=value.get("end_col"),
            )
        except (KeyError, AnalysisContractError, TypeError) as exc:
            raise VacuityTestZkError(f"{name} is malformed: {exc}") from exc
    raise VacuityTestZkError(f"{name} must be SourceSpan or mapping")


def _normalize_source_spans(
    values: Sequence[SourceSpan | Mapping[str, Any]],
    name: str = "source_spans",
) -> tuple[SourceSpan, ...]:
    if not isinstance(values, (list, tuple)):
        raise VacuityTestZkError(f"{name} must be a list")
    if not values:
        raise VacuityTestZkError(f"{name} must not be empty")
    if len(values) > MAX_LIST:
        raise VacuityTestZkError(f"{name} exceeds maximum length")
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
        raise VacuityTestZkError(f"{name} is required")
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
            raise VacuityTestZkError(f"{name} is malformed: {exc}") from exc
    raise VacuityTestZkError(f"{name} must be MinimizedEvidenceBinding or mapping")


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except AssuranceBaseError as exc:
            raise VacuityTestZkError(str(exc)) from exc
    raise VacuityTestZkError(f"{name} must be AssuranceArtifactHeader or mapping")


def _finding_header(
    base: AssuranceArtifactHeader,
    *,
    interface_id: str,
    symbol_ids: Sequence[str],
) -> AssuranceArtifactHeader:
    """Derive a vacuity_finding header from a caller-supplied base header."""

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
    # Preserve authority/execution semantics; pin artifact kind and generator.
    return AssuranceArtifactHeader(
        artifact_kind="vacuity_finding",
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
# Test vacuity subject
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TestAssertionObservation:
    """One assertion observed on a test subject."""

    assertion_id: str
    strength: TestAssertionStrength | str
    expression: str
    observes_behavior: bool
    observes_effects: bool
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "assertion_id",
            "strength",
            "expression",
            "observes_behavior",
            "observes_effects",
            "notes",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "assertion_id", _token(self.assertion_id, "assertion_id")
        )
        strength = _enum(self.strength, TestAssertionStrength, "strength")
        object.__setattr__(self, "strength", strength)
        expression = _text(self.expression, "expression")
        object.__setattr__(self, "expression", expression)
        observes_behavior = _bool(self.observes_behavior, "observes_behavior")
        observes_effects = _bool(self.observes_effects, "observes_effects")
        # Fail closed: strength must be consistent with observation flags.
        if strength == TestAssertionStrength.TAUTOLOGY.value:
            if observes_behavior or observes_effects:
                raise VacuityTestZkError(
                    "tautology assertions cannot observe behavior or effects"
                )
        elif strength == TestAssertionStrength.TYPE_ONLY.value:
            if observes_behavior or observes_effects:
                raise VacuityTestZkError(
                    "type_only assertions cannot observe behavior or effects"
                )
        elif strength == TestAssertionStrength.NON_NULL_ONLY.value:
            if observes_behavior or observes_effects:
                raise VacuityTestZkError(
                    "non_null_only assertions cannot observe behavior or effects"
                )
        elif strength == TestAssertionStrength.BEHAVIORAL.value:
            if not observes_behavior:
                raise VacuityTestZkError(
                    "behavioral assertions require observes_behavior=true"
                )
        elif strength == TestAssertionStrength.EFFECT_OBSERVING.value:
            if not observes_effects:
                raise VacuityTestZkError(
                    "effect_observing assertions require observes_effects=true"
                )
        object.__setattr__(self, "observes_behavior", observes_behavior)
        object.__setattr__(self, "observes_effects", observes_effects)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "strength": self.strength
            if isinstance(self.strength, str)
            else self.strength.value,
            "expression": self.expression,
            "observes_behavior": self.observes_behavior,
            "observes_effects": self.observes_effects,
            "notes": self.notes,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestAssertionObservation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class TestMockObservation:
    """One mock/stub observed on a test subject."""

    mock_id: str
    target_symbol_id: str
    behavior_independent: bool
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "mock_id",
            "target_symbol_id",
            "behavior_independent",
            "notes",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "mock_id", _token(self.mock_id, "mock_id"))
        object.__setattr__(
            self,
            "target_symbol_id",
            _symbol_id(self.target_symbol_id, "target_symbol_id"),
        )
        object.__setattr__(
            self,
            "behavior_independent",
            _bool(self.behavior_independent, "behavior_independent"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "mock_id": self.mock_id,
            "target_symbol_id": self.target_symbol_id,
            "behavior_independent": self.behavior_independent,
            "notes": self.notes,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestMockObservation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class TestVacuitySubject:
    """Closed observation record for test-family vacuity analysis.

    Callers supply factual observations already extracted by static/dynamic
    collectors. This module does not invent reachability or execution facts.
    Missing capability (``observation_complete=false``) fails closed.
    """

    subject_id: str
    claimed_property: str
    symbol_ids: Sequence[str]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    dependency_path: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    assertions: Sequence[TestAssertionObservation | Mapping[str, Any]]
    mocks: Sequence[TestMockObservation | Mapping[str, Any]] = ()
    target_symbol_ids: Sequence[str] = ()
    targets_called: Sequence[str] = ()
    permanent_skip: bool = False
    skip_condition: str | None = None
    fixture_bypasses_production_path: bool = False
    bypassed_path_ids: Sequence[str] = ()
    success_declared_before_effect_observation: bool = False
    subject_cid: str | None = None
    observation_complete: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "subject_id",
            "claimed_property",
            "symbol_ids",
            "source_spans",
            "dependency_path",
            "minimized_evidence",
            "assertions",
            "mocks",
            "target_symbol_ids",
            "targets_called",
            "permanent_skip",
            "skip_condition",
            "fixture_bypasses_production_path",
            "bypassed_path_ids",
            "success_declared_before_effect_observation",
            "subject_cid",
            "observation_complete",
            "notes",
            "metadata",
            "subject_observation_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(
            self,
            "claimed_property",
            _text(self.claimed_property, "claimed_property"),
        )
        symbols = _unique_sorted_tokens(
            list(self.symbol_ids), "symbol_ids", symbol=True
        )
        if not symbols:
            raise VacuityTestZkError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        spans = _normalize_source_spans(list(self.source_spans), "source_spans")
        object.__setattr__(self, "source_spans", spans)
        path = _unique_sorted_tokens(
            list(self.dependency_path), "dependency_path", symbol=True
        )
        if not path:
            raise VacuityTestZkError("dependency_path must not be empty")
        object.__setattr__(self, "dependency_path", path)
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_evidence(self.minimized_evidence),
        )
        assertions = _normalize_assertions(list(self.assertions))
        object.__setattr__(self, "assertions", assertions)
        mocks = _normalize_mocks(list(self.mocks))
        object.__setattr__(self, "mocks", mocks)
        targets = _unique_sorted_tokens(
            list(self.target_symbol_ids), "target_symbol_ids", symbol=True
        )
        object.__setattr__(self, "target_symbol_ids", targets)
        called = _unique_sorted_tokens(
            list(self.targets_called), "targets_called", symbol=True
        )
        unknown_called = sorted(set(called) - set(targets))
        if unknown_called:
            raise VacuityTestZkError(
                "targets_called contains symbols absent from target_symbol_ids: "
                + ", ".join(unknown_called)
            )
        object.__setattr__(self, "targets_called", called)
        permanent_skip = _bool(self.permanent_skip, "permanent_skip")
        object.__setattr__(self, "permanent_skip", permanent_skip)
        object.__setattr__(
            self, "skip_condition", _optional_text(self.skip_condition, "skip_condition")
        )
        if permanent_skip and self.skip_condition is None:
            # Permanent skip without a condition is admitted; condition optional.
            pass
        object.__setattr__(
            self,
            "fixture_bypasses_production_path",
            _bool(
                self.fixture_bypasses_production_path,
                "fixture_bypasses_production_path",
            ),
        )
        bypassed = _unique_sorted_tokens(
            list(self.bypassed_path_ids), "bypassed_path_ids", symbol=True
        )
        if self.fixture_bypasses_production_path and not bypassed:
            raise VacuityTestZkError(
                "fixture_bypasses_production_path requires bypassed_path_ids"
            )
        if not self.fixture_bypasses_production_path and bypassed:
            raise VacuityTestZkError(
                "bypassed_path_ids require fixture_bypasses_production_path=true"
            )
        object.__setattr__(self, "bypassed_path_ids", bypassed)
        object.__setattr__(
            self,
            "success_declared_before_effect_observation",
            _bool(
                self.success_declared_before_effect_observation,
                "success_declared_before_effect_observation",
            ),
        )
        object.__setattr__(
            self, "subject_cid", _optional_cid(self.subject_cid, "subject_cid")
        )
        object.__setattr__(
            self,
            "observation_complete",
            _bool(self.observation_complete, "observation_complete"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TEST_VACUITY_SUBJECT_SCHEMA,
            "subject_id": self.subject_id,
            "claimed_property": self.claimed_property,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "assertions": [item.identity_payload() for item in self.assertions],
            "mocks": [item.identity_payload() for item in self.mocks],
            "target_symbol_ids": list(self.target_symbol_ids),
            "targets_called": list(self.targets_called),
            "permanent_skip": self.permanent_skip,
            "skip_condition": self.skip_condition,
            "fixture_bypasses_production_path": self.fixture_bypasses_production_path,
            "bypassed_path_ids": list(self.bypassed_path_ids),
            "success_declared_before_effect_observation": (
                self.success_declared_before_effect_observation
            ),
            "subject_cid": self.subject_cid,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def subject_observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["source_spans"] = [span.to_dict() for span in self.source_spans]
        value["minimized_evidence"] = self.minimized_evidence.to_dict()
        value["assertions"] = [item.to_dict() for item in self.assertions]
        value["mocks"] = [item.to_dict() for item in self.mocks]
        value["subject_observation_cid"] = self.subject_observation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TestVacuitySubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("subject_observation_cid")
        if payload.pop("schema") != TEST_VACUITY_SUBJECT_SCHEMA:
            raise VacuityTestZkError(
                "unsupported TestVacuitySubject schema version"
            )
        result = cls(
            subject_id=payload["subject_id"],
            claimed_property=payload["claimed_property"],
            symbol_ids=payload["symbol_ids"],
            source_spans=payload["source_spans"],
            dependency_path=payload["dependency_path"],
            minimized_evidence=payload["minimized_evidence"],
            assertions=payload["assertions"],
            mocks=payload["mocks"],
            target_symbol_ids=payload["target_symbol_ids"],
            targets_called=payload["targets_called"],
            permanent_skip=payload["permanent_skip"],
            skip_condition=payload["skip_condition"],
            fixture_bypasses_production_path=payload[
                "fixture_bypasses_production_path"
            ],
            bypassed_path_ids=payload["bypassed_path_ids"],
            success_declared_before_effect_observation=payload[
                "success_declared_before_effect_observation"
            ],
            subject_cid=payload["subject_cid"],
            observation_complete=payload["observation_complete"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.subject_observation_cid:
            raise VacuityTestZkError(
                "TestVacuitySubject subject_observation_cid identity mismatch"
            )
        return result


def _normalize_assertions(
    values: Sequence[TestAssertionObservation | Mapping[str, Any]],
) -> tuple[TestAssertionObservation, ...]:
    if not isinstance(values, (list, tuple)):
        raise VacuityTestZkError("assertions must be a list")
    if len(values) > MAX_ASSERTIONS:
        raise VacuityTestZkError("assertions exceeds maximum length")
    out: list[TestAssertionObservation] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        if isinstance(raw, TestAssertionObservation):
            item = raw
        elif isinstance(raw, Mapping):
            item = TestAssertionObservation.from_dict(raw)
        else:
            raise VacuityTestZkError(
                f"assertions[{index}] must be TestAssertionObservation or mapping"
            )
        if item.assertion_id in seen:
            raise VacuityTestZkError("assertions must have unique assertion_id values")
        seen.add(item.assertion_id)
        out.append(item)
    return tuple(sorted(out, key=lambda item: item.assertion_id))


def _normalize_mocks(
    values: Sequence[TestMockObservation | Mapping[str, Any]],
) -> tuple[TestMockObservation, ...]:
    if not isinstance(values, (list, tuple)):
        raise VacuityTestZkError("mocks must be a list")
    if len(values) > MAX_MOCKS:
        raise VacuityTestZkError("mocks exceeds maximum length")
    out: list[TestMockObservation] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        if isinstance(raw, TestMockObservation):
            item = raw
        elif isinstance(raw, Mapping):
            item = TestMockObservation.from_dict(raw)
        else:
            raise VacuityTestZkError(
                f"mocks[{index}] must be TestMockObservation or mapping"
            )
        if item.mock_id in seen:
            raise VacuityTestZkError("mocks must have unique mock_id values")
        seen.add(item.mock_id)
        out.append(item)
    return tuple(sorted(out, key=lambda item: item.mock_id))


def _normalize_test_subject(
    value: TestVacuitySubject | Mapping[str, Any],
) -> TestVacuitySubject:
    if isinstance(value, TestVacuitySubject):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "subject_observation_cid" in value:
            return TestVacuitySubject.from_dict(value)
        # Admit open construction without schema/cid for analyzer call sites.
        fields = {
            key: value[key]
            for key in TestVacuitySubject._FIELDS
            if key not in {"schema", "subject_observation_cid"} and key in value
        }
        return TestVacuitySubject(**fields)  # type: ignore[arg-type]
    raise VacuityTestZkError("subject must be TestVacuitySubject or mapping")


# ---------------------------------------------------------------------------
# ZK / receipt vacuity subject
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ZkReceiptVacuitySubject:
    """Closed observation record for ZK/receipt/seal vacuity analysis.

    Facts are supplied by collectors. This analyzer never elevates structural
    inclusion, signed aggregation, or caller-supplied keys into direct-execution
    proof. Explicit ``declared_nonclaims`` are preserved on findings.
    """

    subject_id: str
    claimed_property: str
    symbol_ids: Sequence[str]
    source_spans: Sequence[SourceSpan | Mapping[str, Any]]
    dependency_path: Sequence[str]
    minimized_evidence: MinimizedEvidenceBinding | Mapping[str, Any]
    required_fields: Sequence[str]
    bound_fields: Sequence[str]
    source_root_bound: bool
    environment_bound: bool
    required_set_ids: Sequence[str] = ()
    included_set_ids: Sequence[str] = ()
    verification_key_source: VerificationKeySource | str = VerificationKeySource.AUTHORITY
    is_signed_aggregation: bool = False
    claims_direct_execution: bool = False
    changed_unit_ids: Sequence[str] = ()
    sealed_delta_unit_ids: Sequence[str] = ()
    declared_nonclaims: Sequence[str] = ()
    subject_cid: str | None = None
    observation_complete: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "subject_id",
            "claimed_property",
            "symbol_ids",
            "source_spans",
            "dependency_path",
            "minimized_evidence",
            "required_fields",
            "bound_fields",
            "source_root_bound",
            "environment_bound",
            "required_set_ids",
            "included_set_ids",
            "verification_key_source",
            "is_signed_aggregation",
            "claims_direct_execution",
            "changed_unit_ids",
            "sealed_delta_unit_ids",
            "declared_nonclaims",
            "subject_cid",
            "observation_complete",
            "notes",
            "metadata",
            "subject_observation_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(
            self,
            "claimed_property",
            _text(self.claimed_property, "claimed_property"),
        )
        symbols = _unique_sorted_tokens(
            list(self.symbol_ids), "symbol_ids", symbol=True
        )
        if not symbols:
            raise VacuityTestZkError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        spans = _normalize_source_spans(list(self.source_spans), "source_spans")
        object.__setattr__(self, "source_spans", spans)
        path = _unique_sorted_tokens(
            list(self.dependency_path), "dependency_path", symbol=True
        )
        if not path:
            raise VacuityTestZkError("dependency_path must not be empty")
        object.__setattr__(self, "dependency_path", path)
        object.__setattr__(
            self,
            "minimized_evidence",
            _normalize_evidence(self.minimized_evidence),
        )
        required_fields = _unique_sorted_tokens(
            list(self.required_fields), "required_fields"
        )
        bound_fields = _unique_sorted_tokens(list(self.bound_fields), "bound_fields")
        unknown_bound = sorted(set(bound_fields) - set(required_fields))
        # Bound fields may include optional fields beyond required; admit that.
        # But empty names are already rejected.
        del unknown_bound  # reserved for future strict mode
        object.__setattr__(self, "required_fields", required_fields)
        object.__setattr__(self, "bound_fields", bound_fields)
        object.__setattr__(
            self, "source_root_bound", _bool(self.source_root_bound, "source_root_bound")
        )
        object.__setattr__(
            self, "environment_bound", _bool(self.environment_bound, "environment_bound")
        )
        required_sets = _unique_sorted_tokens(
            list(self.required_set_ids), "required_set_ids", symbol=True
        )
        included_sets = _unique_sorted_tokens(
            list(self.included_set_ids), "included_set_ids", symbol=True
        )
        object.__setattr__(self, "required_set_ids", required_sets)
        object.__setattr__(self, "included_set_ids", included_sets)
        object.__setattr__(
            self,
            "verification_key_source",
            _enum(
                self.verification_key_source,
                VerificationKeySource,
                "verification_key_source",
            ),
        )
        object.__setattr__(
            self,
            "is_signed_aggregation",
            _bool(self.is_signed_aggregation, "is_signed_aggregation"),
        )
        object.__setattr__(
            self,
            "claims_direct_execution",
            _bool(self.claims_direct_execution, "claims_direct_execution"),
        )
        changed = _unique_sorted_tokens(
            list(self.changed_unit_ids), "changed_unit_ids", symbol=True, maximum=MAX_UNITS
        )
        sealed = _unique_sorted_tokens(
            list(self.sealed_delta_unit_ids),
            "sealed_delta_unit_ids",
            symbol=True,
            maximum=MAX_UNITS,
        )
        object.__setattr__(self, "changed_unit_ids", changed)
        object.__setattr__(self, "sealed_delta_unit_ids", sealed)
        nonclaims = _unique_sorted_texts(
            list(self.declared_nonclaims),
            "declared_nonclaims",
            maximum=MAX_NONCLAIMS,
        )
        object.__setattr__(self, "declared_nonclaims", nonclaims)
        object.__setattr__(
            self, "subject_cid", _optional_cid(self.subject_cid, "subject_cid")
        )
        object.__setattr__(
            self,
            "observation_complete",
            _bool(self.observation_complete, "observation_complete"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ZK_RECEIPT_VACUITY_SUBJECT_SCHEMA,
            "subject_id": self.subject_id,
            "claimed_property": self.claimed_property,
            "symbol_ids": list(self.symbol_ids),
            "source_spans": [span.identity_payload() for span in self.source_spans],
            "dependency_path": list(self.dependency_path),
            "minimized_evidence": self.minimized_evidence.identity_payload(),
            "required_fields": list(self.required_fields),
            "bound_fields": list(self.bound_fields),
            "source_root_bound": self.source_root_bound,
            "environment_bound": self.environment_bound,
            "required_set_ids": list(self.required_set_ids),
            "included_set_ids": list(self.included_set_ids),
            "verification_key_source": self.verification_key_source
            if isinstance(self.verification_key_source, str)
            else self.verification_key_source.value,
            "is_signed_aggregation": self.is_signed_aggregation,
            "claims_direct_execution": self.claims_direct_execution,
            "changed_unit_ids": list(self.changed_unit_ids),
            "sealed_delta_unit_ids": list(self.sealed_delta_unit_ids),
            "declared_nonclaims": list(self.declared_nonclaims),
            "subject_cid": self.subject_cid,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def subject_observation_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["source_spans"] = [span.to_dict() for span in self.source_spans]
        value["minimized_evidence"] = self.minimized_evidence.to_dict()
        value["subject_observation_cid"] = self.subject_observation_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ZkReceiptVacuitySubject":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("subject_observation_cid")
        if payload.pop("schema") != ZK_RECEIPT_VACUITY_SUBJECT_SCHEMA:
            raise VacuityTestZkError(
                "unsupported ZkReceiptVacuitySubject schema version"
            )
        result = cls(
            subject_id=payload["subject_id"],
            claimed_property=payload["claimed_property"],
            symbol_ids=payload["symbol_ids"],
            source_spans=payload["source_spans"],
            dependency_path=payload["dependency_path"],
            minimized_evidence=payload["minimized_evidence"],
            required_fields=payload["required_fields"],
            bound_fields=payload["bound_fields"],
            source_root_bound=payload["source_root_bound"],
            environment_bound=payload["environment_bound"],
            required_set_ids=payload["required_set_ids"],
            included_set_ids=payload["included_set_ids"],
            verification_key_source=payload["verification_key_source"],
            is_signed_aggregation=payload["is_signed_aggregation"],
            claims_direct_execution=payload["claims_direct_execution"],
            changed_unit_ids=payload["changed_unit_ids"],
            sealed_delta_unit_ids=payload["sealed_delta_unit_ids"],
            declared_nonclaims=payload["declared_nonclaims"],
            subject_cid=payload["subject_cid"],
            observation_complete=payload["observation_complete"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.subject_observation_cid:
            raise VacuityTestZkError(
                "ZkReceiptVacuitySubject subject_observation_cid identity mismatch"
            )
        return result


def _normalize_zk_subject(
    value: ZkReceiptVacuitySubject | Mapping[str, Any],
) -> ZkReceiptVacuitySubject:
    if isinstance(value, ZkReceiptVacuitySubject):
        return value
    if isinstance(value, Mapping):
        if "schema" in value or "subject_observation_cid" in value:
            return ZkReceiptVacuitySubject.from_dict(value)
        fields = {
            key: value[key]
            for key in ZkReceiptVacuitySubject._FIELDS
            if key not in {"schema", "subject_observation_cid"} and key in value
        }
        return ZkReceiptVacuitySubject(**fields)  # type: ignore[arg-type]
    raise VacuityTestZkError("subject must be ZkReceiptVacuitySubject or mapping")


# ---------------------------------------------------------------------------
# Analysis result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VacuityAnalysisResult:
    """Deterministic result of one vacuity-family analysis run.

    Interface: ``VacuityAnalysisResult@1``
    """

    interface_id: str
    vacuity_family: VacuityFamily | str
    subject_id: str
    subject_observation_cid: str
    findings: Sequence[VacuityFinding | Mapping[str, Any]]
    finding_cids: Sequence[str]
    residual_properties: Sequence[str]
    precise_nonclaims: Sequence[str]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "vacuity_family",
            "subject_id",
            "subject_observation_cid",
            "findings",
            "finding_cids",
            "residual_properties",
            "precise_nonclaims",
            "notes",
            "metadata",
            "result_cid",
        }
    )

    def __post_init__(self) -> None:
        interface_id = _text(self.interface_id, "interface_id")
        if interface_id not in {
            ANALYZE_TEST_VACUITY_INTERFACE,
            ANALYZE_ZK_RECEIPT_VACUITY_INTERFACE,
        }:
            raise VacuityTestZkError(
                "interface_id must be analyze_test_vacuity@1 or "
                "analyze_zk_receipt_vacuity@1"
            )
        object.__setattr__(self, "interface_id", interface_id)
        family = _enum(self.vacuity_family, VacuityFamily, "vacuity_family")
        if interface_id == ANALYZE_TEST_VACUITY_INTERFACE:
            if family != VacuityFamily.TEST.value:
                raise VacuityTestZkError(
                    "analyze_test_vacuity@1 requires vacuity_family=test"
                )
        else:
            if family != VacuityFamily.ZK_RECEIPT.value:
                raise VacuityTestZkError(
                    "analyze_zk_receipt_vacuity@1 requires vacuity_family=zk_receipt"
                )
        object.__setattr__(self, "vacuity_family", family)
        object.__setattr__(self, "subject_id", _token(self.subject_id, "subject_id"))
        object.__setattr__(
            self,
            "subject_observation_cid",
            _cid(self.subject_observation_cid, "subject_observation_cid"),
        )
        findings = _normalize_findings(list(self.findings))
        if len(findings) > MAX_FINDINGS:
            raise VacuityTestZkError("findings exceeds maximum length")
        object.__setattr__(self, "findings", findings)
        claimed_cids = _unique_sorted_texts(
            list(self.finding_cids), "finding_cids", maximum=MAX_FINDINGS
        )
        actual_cids = tuple(sorted(item.finding_cid for item in findings))
        if claimed_cids != actual_cids:
            raise VacuityTestZkError(
                "finding_cids must exactly match sorted finding identities"
            )
        object.__setattr__(self, "finding_cids", claimed_cids)
        residuals = _unique_sorted_texts(
            list(self.residual_properties), "residual_properties"
        )
        nonclaims = _unique_sorted_texts(
            list(self.precise_nonclaims), "precise_nonclaims", maximum=MAX_NONCLAIMS
        )
        # Every finding contributes a residual and a nonclaim.
        if findings:
            if not residuals:
                raise VacuityTestZkError(
                    "residual_properties must restate what remains proven"
                )
            if not nonclaims:
                raise VacuityTestZkError(
                    "precise_nonclaims must restate what is not proven"
                )
        object.__setattr__(self, "residual_properties", residuals)
        object.__setattr__(self, "precise_nonclaims", nonclaims)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": VACUITY_ANALYSIS_RESULT_SCHEMA,
            "interface_id": self.interface_id,
            "vacuity_family": self.vacuity_family
            if isinstance(self.vacuity_family, str)
            else self.vacuity_family.value,
            "subject_id": self.subject_id,
            "subject_observation_cid": self.subject_observation_cid,
            "findings": [item.identity_payload() for item in self.findings],
            "finding_cids": list(self.finding_cids),
            "residual_properties": list(self.residual_properties),
            "precise_nonclaims": list(self.precise_nonclaims),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema": VACUITY_ANALYSIS_RESULT_SCHEMA,
            "interface_id": self.interface_id,
            "vacuity_family": self.vacuity_family
            if isinstance(self.vacuity_family, str)
            else self.vacuity_family.value,
            "subject_id": self.subject_id,
            "subject_observation_cid": self.subject_observation_cid,
            "findings": [item.to_dict() for item in self.findings],
            "finding_cids": list(self.finding_cids),
            "residual_properties": list(self.residual_properties),
            "precise_nonclaims": list(self.precise_nonclaims),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "result_cid": self.result_cid,
        }
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VacuityAnalysisResult":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("result_cid")
        if payload.pop("schema") != VACUITY_ANALYSIS_RESULT_SCHEMA:
            raise VacuityTestZkError(
                "unsupported VacuityAnalysisResult schema version"
            )
        result = cls(
            interface_id=payload["interface_id"],
            vacuity_family=payload["vacuity_family"],
            subject_id=payload["subject_id"],
            subject_observation_cid=payload["subject_observation_cid"],
            findings=payload["findings"],
            finding_cids=payload["finding_cids"],
            residual_properties=payload["residual_properties"],
            precise_nonclaims=payload["precise_nonclaims"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.result_cid:
            raise VacuityTestZkError(
                "VacuityAnalysisResult result_cid identity mismatch"
            )
        return result


def _normalize_findings(
    values: Sequence[VacuityFinding | Mapping[str, Any]],
) -> tuple[VacuityFinding, ...]:
    if not isinstance(values, (list, tuple)):
        raise VacuityTestZkError("findings must be a list")
    out: list[VacuityFinding] = []
    for index, raw in enumerate(values):
        if isinstance(raw, VacuityFinding):
            item = raw
        elif isinstance(raw, Mapping):
            try:
                item = VacuityFinding.from_dict(raw)
            except AnalysisContractError as exc:
                raise VacuityTestZkError(
                    f"findings[{index}] is malformed: {exc}"
                ) from exc
        else:
            raise VacuityTestZkError(
                f"findings[{index}] must be VacuityFinding or mapping"
            )
        try:
            verify_vacuity_finding_identity(item)
        except AnalysisContractError as exc:
            raise VacuityTestZkError(str(exc)) from exc
        out.append(item)
    return tuple(sorted(out, key=lambda item: (item.vacuity_kind, item.finding_id)))


# ---------------------------------------------------------------------------
# Finding construction
# ---------------------------------------------------------------------------


def _make_finding(
    *,
    header: AssuranceArtifactHeader,
    finding_id: str,
    family: VacuityFamily,
    kind: VacuityKind,
    subject_id: str,
    subject_cid: str | None,
    vacuous_claim: str,
    remains: str,
    not_proven: str,
    symbol_ids: Sequence[str],
    source_spans: Sequence[SourceSpan],
    dependency_path: Sequence[str],
    evidence: MinimizedEvidenceBinding,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> VacuityFinding:
    return VacuityFinding(
        header=header,
        finding_id=finding_id,
        vacuity_family=family,
        vacuity_kind=kind,
        subject_id=subject_id,
        subject_cid=subject_cid,
        vacuous_claim=vacuous_claim,
        what_remains_proven=remains,
        what_is_not_proven=not_proven,
        symbol_ids=symbol_ids,
        source_spans=source_spans,
        dependency_path=dependency_path,
        minimized_evidence=evidence,
        notes=notes,
        metadata=dict(metadata or {}),
    )


def _is_tautology_expression(expression: str) -> bool:
    stripped = expression.strip().strip("()[]{} ")
    if stripped in _TAUTOLOGY_MARKERS:
        return True
    lower = stripped.lower()
    if lower in {m.lower() for m in _TAUTOLOGY_MARKERS}:
        return True
    # Classic identity tautologies.
    if re.fullmatch(r"(.+)\s*==\s*\1", stripped):
        return True
    if re.fullmatch(r"(.+)\s+is\s+\1", stripped, flags=re.IGNORECASE):
        return True
    return False


# ---------------------------------------------------------------------------
# analyze_test_vacuity@1
# ---------------------------------------------------------------------------


def analyze_test_vacuity(
    subject: TestVacuitySubject | Mapping[str, Any],
    header: AssuranceArtifactHeader | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> VacuityAnalysisResult:
    """Detect test-family vacuity and emit precise residual / nonclaim findings.

    Interface: ``analyze_test_vacuity@1``

    Fail-closed when observation is incomplete or the subject cannot be sealed.
    Deterministic: same sealed subject and header inputs always yield the same
    result CID and finding set.
    """

    sealed_subject = _normalize_test_subject(subject)
    if not sealed_subject.observation_complete:
        raise VacuityTestZkError(
            "analyze_test_vacuity fails closed when observation_complete is false"
        )
    base_header = _header(header)
    finding_header = _finding_header(
        base_header,
        interface_id=ANALYZE_TEST_VACUITY_INTERFACE,
        symbol_ids=sealed_subject.symbol_ids,
    )
    findings: list[VacuityFinding] = []
    claim = sealed_subject.claimed_property

    # --- tautology ---
    tautology_assertions = [
        item
        for item in sealed_subject.assertions
        if item.strength == TestAssertionStrength.TAUTOLOGY.value
        or _is_tautology_expression(item.expression)
    ]
    if tautology_assertions:
        expressions = ", ".join(
            sorted({item.expression for item in tautology_assertions})
        )
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.tautology",
                family=VacuityFamily.TEST,
                kind=VacuityKind.TAUTOLOGY,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"expressions evaluate without raising: {expressions}"
                ),
                not_proven=(
                    f"claimed property is not established by tautological "
                    f"assertions: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="tautology assertions discharge no behavioral obligation",
                metadata={"assertion_ids": [a.assertion_id for a in tautology_assertions]},
            )
        )

    # --- type-only ---
    if sealed_subject.assertions:
        all_type_only = all(
            item.strength
            in {
                TestAssertionStrength.TYPE_ONLY.value,
                TestAssertionStrength.TAUTOLOGY.value,
            }
            for item in sealed_subject.assertions
        )
        any_type_only = any(
            item.strength == TestAssertionStrength.TYPE_ONLY.value
            for item in sealed_subject.assertions
        )
        if all_type_only and any_type_only:
            findings.append(
                _make_finding(
                    header=finding_header,
                    finding_id=f"{sealed_subject.subject_id}.type_only",
                    family=VacuityFamily.TEST,
                    kind=VacuityKind.TYPE_ONLY_ASSERTION,
                    subject_id=sealed_subject.subject_id,
                    subject_cid=sealed_subject.subject_cid,
                    vacuous_claim=claim,
                    remains=(
                        "runtime type/isinstance checks complete without TypeError"
                    ),
                    not_proven=(
                        f"behavioral property is not proven by type-only "
                        f"assertions: {claim}"
                    ),
                    symbol_ids=sealed_subject.symbol_ids,
                    source_spans=sealed_subject.source_spans,
                    dependency_path=sealed_subject.dependency_path,
                    evidence=sealed_subject.minimized_evidence,
                    notes="type-only assertions do not constrain values or effects",
                )
            )

        # --- non-null only ---
        all_non_null = all(
            item.strength
            in {
                TestAssertionStrength.NON_NULL_ONLY.value,
                TestAssertionStrength.TAUTOLOGY.value,
            }
            for item in sealed_subject.assertions
        )
        any_non_null = any(
            item.strength == TestAssertionStrength.NON_NULL_ONLY.value
            for item in sealed_subject.assertions
        )
        if all_non_null and any_non_null:
            findings.append(
                _make_finding(
                    header=finding_header,
                    finding_id=f"{sealed_subject.subject_id}.non_null_only",
                    family=VacuityFamily.TEST,
                    kind=VacuityKind.NON_NULL_ONLY_ASSERTION,
                    subject_id=sealed_subject.subject_id,
                    subject_cid=sealed_subject.subject_cid,
                    vacuous_claim=claim,
                    remains="observed values are not None at assertion sites",
                    not_proven=(
                        f"semantic invariants beyond non-null are not proven: {claim}"
                    ),
                    symbol_ids=sealed_subject.symbol_ids,
                    source_spans=sealed_subject.source_spans,
                    dependency_path=sealed_subject.dependency_path,
                    evidence=sealed_subject.minimized_evidence,
                    notes="non-null checks alone never prove authorization or effects",
                )
            )

    # --- behavior-independent mocks ---
    independent_mocks = [
        item for item in sealed_subject.mocks if item.behavior_independent
    ]
    if independent_mocks and sealed_subject.target_symbol_ids:
        mock_targets = ", ".join(
            sorted({item.target_symbol_id for item in independent_mocks})
        )
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.behavior_independent_mock",
                family=VacuityFamily.TEST,
                kind=VacuityKind.BEHAVIOR_INDEPENDENT_MOCK,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"test interacts with behavior-independent mocks for: {mock_targets}"
                ),
                not_proven=(
                    f"production behavior of mocked targets is not proven: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="mocks that ignore production semantics vacate target proofs",
                metadata={
                    "mock_ids": [item.mock_id for item in independent_mocks],
                },
            )
        )

    # --- uncalled target ---
    if sealed_subject.target_symbol_ids:
        uncalled = sorted(
            set(sealed_subject.target_symbol_ids) - set(sealed_subject.targets_called)
        )
        if uncalled:
            findings.append(
                _make_finding(
                    header=finding_header,
                    finding_id=f"{sealed_subject.subject_id}.uncalled_target",
                    family=VacuityFamily.TEST,
                    kind=VacuityKind.UNCALLED_TARGET,
                    subject_id=sealed_subject.subject_id,
                    subject_cid=sealed_subject.subject_cid,
                    vacuous_claim=claim,
                    remains=(
                        "test completes without invoking declared production targets"
                    ),
                    not_proven=(
                        "declared targets were never exercised: "
                        + ", ".join(uncalled)
                        + f"; property not proven: {claim}"
                    ),
                    symbol_ids=sealed_subject.symbol_ids,
                    source_spans=sealed_subject.source_spans,
                    dependency_path=sealed_subject.dependency_path,
                    evidence=sealed_subject.minimized_evidence,
                    metadata={"uncalled_targets": uncalled},
                )
            )

    # --- permanent skip ---
    if sealed_subject.permanent_skip:
        condition = sealed_subject.skip_condition or "unconditional permanent skip"
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.permanent_skip",
                family=VacuityFamily.TEST,
                kind=VacuityKind.PERMANENT_SKIP,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=f"skip condition is recognized: {condition}",
                not_proven=(
                    f"skipped test body does not prove claimed property: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="permanent skips contribute zero detection power",
            )
        )

    # --- path-bypassing fixtures ---
    if sealed_subject.fixture_bypasses_production_path:
        paths = ", ".join(sealed_subject.bypassed_path_ids)
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.bypassing_fixture",
                family=VacuityFamily.TEST,
                kind=VacuityKind.BYPASSING_FIXTURE,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    f"fixture setup succeeds while bypassing production paths: {paths}"
                ),
                not_proven=(
                    f"bypassed production paths are not exercised; property not "
                    f"proven on those paths: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                metadata={"bypassed_path_ids": list(sealed_subject.bypassed_path_ids)},
            )
        )

    # --- early success / success before effect observation ---
    if sealed_subject.success_declared_before_effect_observation:
        has_effect_observation = any(
            item.observes_effects for item in sealed_subject.assertions
        )
        if not has_effect_observation:
            findings.append(
                _make_finding(
                    header=finding_header,
                    finding_id=f"{sealed_subject.subject_id}.success_before_effect",
                    family=VacuityFamily.TEST,
                    kind=VacuityKind.SUCCESS_BEFORE_EFFECT_OBSERVATION,
                    subject_id=sealed_subject.subject_id,
                    subject_cid=sealed_subject.subject_cid,
                    vacuous_claim=claim,
                    remains=(
                        "test reports success before any effect-observing assertion"
                    ),
                    not_proven=(
                        f"side effects and postconditions are not observed; "
                        f"property not proven: {claim}"
                    ),
                    symbol_ids=sealed_subject.symbol_ids,
                    source_spans=sealed_subject.source_spans,
                    dependency_path=sealed_subject.dependency_path,
                    evidence=sealed_subject.minimized_evidence,
                    notes="early success vacates effect and durability claims",
                )
            )

    findings_sorted = tuple(
        sorted(findings, key=lambda item: (item.vacuity_kind, item.finding_id))
    )
    residuals = tuple(sorted({item.what_remains_proven for item in findings_sorted}))
    nonclaims = tuple(sorted({item.what_is_not_proven for item in findings_sorted}))
    result_metadata = dict(metadata or {})
    result_metadata.setdefault(
        "subject_observation_cid", sealed_subject.subject_observation_cid
    )
    return VacuityAnalysisResult(
        interface_id=ANALYZE_TEST_VACUITY_INTERFACE,
        vacuity_family=VacuityFamily.TEST,
        subject_id=sealed_subject.subject_id,
        subject_observation_cid=sealed_subject.subject_observation_cid,
        findings=findings_sorted,
        finding_cids=tuple(sorted(item.finding_cid for item in findings_sorted)),
        residual_properties=residuals,
        precise_nonclaims=nonclaims,
        notes=_optional_text(notes, "notes") if notes is not None else None,
        metadata=result_metadata,
    )


# ---------------------------------------------------------------------------
# analyze_zk_receipt_vacuity@1
# ---------------------------------------------------------------------------


def analyze_zk_receipt_vacuity(
    subject: ZkReceiptVacuitySubject | Mapping[str, Any],
    header: AssuranceArtifactHeader | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> VacuityAnalysisResult:
    """Detect ZK/receipt/seal vacuity with precise residual nonclaims.

    Interface: ``analyze_zk_receipt_vacuity@1``

    Structural inclusion, signed aggregation authenticity, and caller-selected
    verification keys never elevate to direct-execution or completeness proof.
    Declared nonclaims on the subject are merged into precise_nonclaims.
    """

    sealed_subject = _normalize_zk_subject(subject)
    if not sealed_subject.observation_complete:
        raise VacuityTestZkError(
            "analyze_zk_receipt_vacuity fails closed when observation_complete "
            "is false"
        )
    base_header = _header(header)
    finding_header = _finding_header(
        base_header,
        interface_id=ANALYZE_ZK_RECEIPT_VACUITY_INTERFACE,
        symbol_ids=sealed_subject.symbol_ids,
    )
    findings: list[VacuityFinding] = []
    claim = sealed_subject.claimed_property
    declared = list(sealed_subject.declared_nonclaims)

    # --- unbound required fields ---
    unbound_fields = sorted(
        set(sealed_subject.required_fields) - set(sealed_subject.bound_fields)
    )
    if unbound_fields:
        field_list = ", ".join(unbound_fields)
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.unbound_required_field",
                family=VacuityFamily.ZK_RECEIPT,
                kind=VacuityKind.UNBOUND_REQUIRED_FIELD,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    "receipt schema admits required field names but does not bind "
                    f"values for: {field_list}"
                ),
                not_proven=(
                    f"properties depending on unbound required fields are not "
                    f"proven: {field_list}; claimed: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                metadata={"unbound_fields": unbound_fields},
            )
        )

    # --- unbound source root ---
    if not sealed_subject.source_root_bound:
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.unbound_source",
                family=VacuityFamily.ZK_RECEIPT,
                kind=VacuityKind.UNBOUND_SOURCE,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    "receipt structure validates without a bound source root CID"
                ),
                not_proven=(
                    f"source-rooted authenticity and content binding are not "
                    f"proven: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes="unbound source roots never prove repository-state linkage",
            )
        )

    # --- unbound environment ---
    if not sealed_subject.environment_bound:
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.unbound_environment",
                family=VacuityFamily.ZK_RECEIPT,
                kind=VacuityKind.UNBOUND_ENVIRONMENT,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    "receipt structure validates without a bound environment CID"
                ),
                not_proven=(
                    f"environment-conditioned execution and tool bindings are not "
                    f"proven: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
            )
        )

    # --- inclusion without required-set completeness ---
    if sealed_subject.required_set_ids:
        missing_sets = sorted(
            set(sealed_subject.required_set_ids)
            - set(sealed_subject.included_set_ids)
        )
        if missing_sets or (
            sealed_subject.included_set_ids
            and set(sealed_subject.included_set_ids)
            != set(sealed_subject.required_set_ids)
        ):
            # Inclusion of a proper subset without completeness is vacuous.
            included = ", ".join(sealed_subject.included_set_ids) or "(none)"
            missing = ", ".join(missing_sets) if missing_sets else "(set mismatch)"
            findings.append(
                _make_finding(
                    header=finding_header,
                    finding_id=f"{sealed_subject.subject_id}.inclusion_without_completeness",
                    family=VacuityFamily.ZK_RECEIPT,
                    kind=VacuityKind.INCLUSION_WITHOUT_COMPLETENESS,
                    subject_id=sealed_subject.subject_id,
                    subject_cid=sealed_subject.subject_cid,
                    vacuous_claim=claim,
                    remains=(
                        f"included set membership is witnessed for: {included}"
                    ),
                    not_proven=(
                        f"required-set completeness is not proven; missing or "
                        f"mismatched sets: {missing}; claimed: {claim}"
                    ),
                    symbol_ids=sealed_subject.symbol_ids,
                    source_spans=sealed_subject.source_spans,
                    dependency_path=sealed_subject.dependency_path,
                    evidence=sealed_subject.minimized_evidence,
                    metadata={
                        "required_set_ids": list(sealed_subject.required_set_ids),
                        "included_set_ids": list(sealed_subject.included_set_ids),
                        "missing_set_ids": missing_sets,
                    },
                )
            )

    # --- caller-selected / unbound verification key ---
    key_source = sealed_subject.verification_key_source
    if key_source in {
        VerificationKeySource.CALLER.value,
        VerificationKeySource.UNBOUND.value,
    }:
        remains = (
            "verification key identity is recorded as caller-supplied"
            if key_source == VerificationKeySource.CALLER.value
            else "verification key is unbound on the receipt subject"
        )
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.caller_selected_verification_key",
                family=VacuityFamily.ZK_RECEIPT,
                kind=VacuityKind.CALLER_SELECTED_VERIFICATION_KEY,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=remains,
                not_proven=(
                    "authority-bound verification under a non-caller key is not "
                    f"proven; claimed: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes=(
                    "caller-selected keys never establish independent attestation "
                    "authority"
                ),
                metadata={"verification_key_source": key_source},
            )
        )

    # --- signed aggregation presented as direct execution ---
    if sealed_subject.is_signed_aggregation and sealed_subject.claims_direct_execution:
        findings.append(
            _make_finding(
                header=finding_header,
                finding_id=f"{sealed_subject.subject_id}.signed_aggregation_as_execution",
                family=VacuityFamily.ZK_RECEIPT,
                kind=VacuityKind.SIGNED_AGGREGATION_AS_EXECUTION,
                subject_id=sealed_subject.subject_id,
                subject_cid=sealed_subject.subject_cid,
                vacuous_claim=claim,
                remains=(
                    "signed aggregation of admitted receipt digests authenticates "
                    "under the bound verification key"
                ),
                not_proven=(
                    "direct execution of sealed units under the campaign "
                    f"environment is not proven by aggregation alone: {claim}"
                ),
                symbol_ids=sealed_subject.symbol_ids,
                source_spans=sealed_subject.source_spans,
                dependency_path=sealed_subject.dependency_path,
                evidence=sealed_subject.minimized_evidence,
                notes=(
                    "signed aggregation is authenticity evidence, not live "
                    "execution evidence"
                ),
            )
        )

    # --- missing delta seal units ---
    if sealed_subject.changed_unit_ids:
        missing_units = sorted(
            set(sealed_subject.changed_unit_ids)
            - set(sealed_subject.sealed_delta_unit_ids)
        )
        if missing_units:
            missing_list = ", ".join(missing_units)
            findings.append(
                _make_finding(
                    header=finding_header,
                    finding_id=f"{sealed_subject.subject_id}.missing_delta_seal_unit",
                    family=VacuityFamily.ZK_RECEIPT,
                    kind=VacuityKind.MISSING_DELTA_SEAL_UNIT,
                    subject_id=sealed_subject.subject_id,
                    subject_cid=sealed_subject.subject_cid,
                    vacuous_claim=claim,
                    remains=(
                        "delta seal covers a proper subset of changed units"
                    ),
                    not_proven=(
                        f"changed units omitted from the delta seal are not "
                        f"sealed: {missing_list}; claimed: {claim}"
                    ),
                    symbol_ids=sealed_subject.symbol_ids,
                    source_spans=sealed_subject.source_spans,
                    dependency_path=sealed_subject.dependency_path,
                    evidence=sealed_subject.minimized_evidence,
                    metadata={"missing_delta_units": missing_units},
                )
            )

    findings_sorted = tuple(
        sorted(findings, key=lambda item: (item.vacuity_kind, item.finding_id))
    )
    residuals = tuple(sorted({item.what_remains_proven for item in findings_sorted}))
    nonclaims = sorted({item.what_is_not_proven for item in findings_sorted})
    # Merge declared nonclaims; never drop caller-supplied precise nonclaims.
    for item in declared:
        if item not in nonclaims:
            nonclaims.append(item)
    nonclaims_tuple = tuple(sorted(nonclaims))
    result_metadata = dict(metadata or {})
    result_metadata.setdefault(
        "subject_observation_cid", sealed_subject.subject_observation_cid
    )
    if declared:
        result_metadata["declared_nonclaims"] = list(declared)
    return VacuityAnalysisResult(
        interface_id=ANALYZE_ZK_RECEIPT_VACUITY_INTERFACE,
        vacuity_family=VacuityFamily.ZK_RECEIPT,
        subject_id=sealed_subject.subject_id,
        subject_observation_cid=sealed_subject.subject_observation_cid,
        findings=findings_sorted,
        finding_cids=tuple(sorted(item.finding_cid for item in findings_sorted)),
        residual_properties=residuals,
        precise_nonclaims=nonclaims_tuple,
        notes=_optional_text(notes, "notes") if notes is not None else None,
        metadata=result_metadata,
    )


def verify_vacuity_analysis_result_identity(
    result: VacuityAnalysisResult | Mapping[str, Any],
) -> str:
    """Recompute and return the result CID; raise on forged input."""

    if isinstance(result, VacuityAnalysisResult):
        sealed = result
    elif isinstance(result, Mapping):
        sealed = VacuityAnalysisResult.from_dict(result)
    else:
        raise VacuityTestZkError(
            "result must be VacuityAnalysisResult or mapping"
        )
    for finding in sealed.findings:
        verify_vacuity_finding_identity(finding)
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.result_cid:
        raise VacuityTestZkError(
            "result_cid identity mismatch with recomputed identity"
        )
    return recomputed


def test_assertion_strengths() -> tuple[str, ...]:
    """Return the closed test assertion-strength vocabulary."""

    return tuple(item.value for item in TestAssertionStrength)


def verification_key_sources() -> tuple[str, ...]:
    """Return the closed verification-key source vocabulary."""

    return tuple(item.value for item in VerificationKeySource)


__all__ = [
    "ANALYZE_TEST_VACUITY_INTERFACE",
    "ANALYZE_ZK_RECEIPT_VACUITY_INTERFACE",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "TEST_VACUITY_SUBJECT_SCHEMA",
    "VACUITY_ANALYSIS_RESULT_INTERFACE",
    "VACUITY_ANALYSIS_RESULT_SCHEMA",
    "ZK_RECEIPT_VACUITY_SUBJECT_SCHEMA",
    "TestAssertionObservation",
    "TestAssertionStrength",
    "TestMockObservation",
    "TestVacuitySubject",
    "VacuityAnalysisResult",
    "VacuityTestZkError",
    "VerificationKeySource",
    "ZkReceiptVacuitySubject",
    "analyze_test_vacuity",
    "analyze_zk_receipt_vacuity",
    "test_assertion_strengths",
    "verification_key_sources",
    "verify_vacuity_analysis_result_identity",
]
