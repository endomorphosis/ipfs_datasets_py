"""Expected detection-set construction from semantic dependencies (AAE-023).

Interface surface:

* ``predict_detection_set`` — build a sealed ``ExpectedDetectionSet@1`` for one
  mutation candidate from an assurance-manifest detector catalog and a
  semantic-dependency slice.

Every predicted detector binds:

* the violated claim;
* why the detector should observe the violation;
* the connecting source/proof dependency path;
* required versus optional strength;
* expected terminal status;
* exact detector identity and revision.

This module is pure and deterministic. It does not open a store, mutate
worktrees, execute detectors, or change production policy.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from hashlib import blake2b
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
    ArtifactProvenance,
    AssuranceArtifactHeader,
    AssuranceBaseError,
    AssuranceTerminalStatus,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    VersionBinding,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.execution_contracts import (
    MAX_DETECTORS,
    MAX_DEPENDENCY_PATH,
    DetectorKind,
    DetectorPrediction,
    DetectorStrength,
    ExecutionContractError,
    ExpectedDetectionSet,
    verify_detection_set_identity,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    MAX_PROPERTY_CLASSES,
    MAX_TOKEN_LIST,
    MutationCandidate,
    MutationContractError,
    MutationRiskClass,
    PropertyClass,
)

# ---------------------------------------------------------------------------
# Schema / interface constants
# ---------------------------------------------------------------------------

PREDICT_DETECTION_SET_INTERFACE: Final[str] = "predict_detection_set@1"

DETECTOR_CATALOG_ENTRY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-detector-catalog-entry@1"
)
SEMANTIC_DEPENDENCY_EDGE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-semantic-dependency-edge@1"
)
CLAIM_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-detection-claim-binding@1"
)
DETECTION_ASSURANCE_MANIFEST_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-detection-manifest@1"
)
DETECTION_ASSURANCE_MANIFEST_INTERFACE: Final[str] = "DetectionAssuranceManifest@1"

GENERATOR_ID: Final[str] = "detection_prediction"
GENERATOR_VERSION: Final[str] = "1.0.0"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CLAIMS: Final[int] = 4_096
MAX_EDGES: Final[int] = 16_384
MAX_ANCHORS: Final[int] = 256
MAX_PATH_SEARCH_NODES: Final[int] = 4_096

# Synthetic detector pins used when policy requests structural fallbacks.
SYNTHETIC_TYPE_CHECK_ID: Final[str] = "type.type_check"
SYNTHETIC_TYPE_CHECK_REVISION: Final[str] = "1.0.0"
SYNTHETIC_FULL_SUITE_ID: Final[str] = "suite.full_suite"
SYNTHETIC_FULL_SUITE_REVISION: Final[str] = "1.0.0"
SYNTHETIC_SEAL_ID: Final[str] = "seal.incremental"
SYNTHETIC_SEAL_REVISION: Final[str] = "1.0.0"
SYNTHETIC_HUMAN_REVIEW_ID: Final[str] = "human.review"
SYNTHETIC_HUMAN_REVIEW_REVISION: Final[str] = "1.0.0"

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)
_REPOSITORY_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,255}$"
)

# Property classes that strongly imply type/static structural detection.
_TYPE_CHECK_PROPERTY_CLASSES: Final[frozenset[str]] = frozenset(
    {
        PropertyClass.SCHEMA_CONTRACT.value,
        PropertyClass.INTERFACE_CONTRACT.value,
        PropertyClass.DATA_INTEGRITY.value,
    }
)

# Property classes that strongly imply formal/seal detection.
_FORMAL_PROPERTY_CLASSES: Final[frozenset[str]] = frozenset(
    {
        PropertyClass.PROOF_ADEQUACY.value,
        PropertyClass.RECEIPT_AUTHENTICITY.value,
        PropertyClass.CAPSULE_COMPLETENESS.value,
    }
)

# Risk classes that warrant optional full-suite fallback and human review.
_HIGH_RISK_CLASSES: Final[frozenset[str]] = frozenset(
    {
        MutationRiskClass.CRITICAL_SECURITY.value,
        MutationRiskClass.AUTHORIZATION.value,
        MutationRiskClass.FINANCIAL_LEGAL.value,
        MutationRiskClass.DURABILITY.value,
        MutationRiskClass.DISTRIBUTED_TRANSITION.value,
        MutationRiskClass.PROOF_RECEIPT_TRUST.value,
        MutationRiskClass.CRITICAL_INVARIANT.value,
        MutationRiskClass.HIGH.value,
    }
)

# Detector kinds preferred for each property class (catalog filtering aid).
PROPERTY_CLASS_DETECTOR_KINDS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        PropertyClass.CONTROL_INVARIANT.value: (
            DetectorKind.UNIT_TEST.value,
            DetectorKind.PROPERTY_TEST.value,
            DetectorKind.STATIC_RULE.value,
            DetectorKind.RUNTIME_INVARIANT.value,
        ),
        PropertyClass.DATA_INTEGRITY.value: (
            DetectorKind.TYPE_CHECK.value,
            DetectorKind.UNIT_TEST.value,
            DetectorKind.STATIC_RULE.value,
        ),
        PropertyClass.SCHEMA_CONTRACT.value: (
            DetectorKind.TYPE_CHECK.value,
            DetectorKind.STATIC_RULE.value,
            DetectorKind.UNIT_TEST.value,
        ),
        PropertyClass.INTERFACE_CONTRACT.value: (
            DetectorKind.TYPE_CHECK.value,
            DetectorKind.STATIC_RULE.value,
            DetectorKind.INTEGRATION_TEST.value,
        ),
        PropertyClass.SIDE_EFFECT_OBLIGATION.value: (
            DetectorKind.UNIT_TEST.value,
            DetectorKind.INTEGRATION_TEST.value,
            DetectorKind.RUNTIME_INVARIANT.value,
        ),
        PropertyClass.ERROR_HANDLING.value: (
            DetectorKind.UNIT_TEST.value,
            DetectorKind.PROPERTY_TEST.value,
            DetectorKind.STATIC_RULE.value,
        ),
        PropertyClass.RETRY_BUDGET.value: (
            DetectorKind.UNIT_TEST.value,
            DetectorKind.PROPERTY_TEST.value,
            DetectorKind.RUNTIME_INVARIANT.value,
        ),
        PropertyClass.AUTHORIZATION.value: (
            DetectorKind.STATIC_RULE.value,
            DetectorKind.POLICY_RULE.value,
            DetectorKind.UNIT_TEST.value,
            DetectorKind.FORMAL_OBLIGATION.value,
        ),
        PropertyClass.POLICY_CONSTRAINT.value: (
            DetectorKind.POLICY_RULE.value,
            DetectorKind.STATIC_RULE.value,
            DetectorKind.UNIT_TEST.value,
        ),
        PropertyClass.STATE_TRANSITION.value: (
            DetectorKind.UNIT_TEST.value,
            DetectorKind.INTEGRATION_TEST.value,
            DetectorKind.PROPERTY_TEST.value,
            DetectorKind.FORMAL_OBLIGATION.value,
        ),
        PropertyClass.DURABILITY.value: (
            DetectorKind.INTEGRATION_TEST.value,
            DetectorKind.PROPERTY_TEST.value,
            DetectorKind.RUNTIME_INVARIANT.value,
        ),
        PropertyClass.STORAGE_INTEGRITY.value: (
            DetectorKind.UNIT_TEST.value,
            DetectorKind.INTEGRATION_TEST.value,
            DetectorKind.STATIC_RULE.value,
        ),
        PropertyClass.TEST_ADEQUACY.value: (
            DetectorKind.UNIT_TEST.value,
            DetectorKind.PROPERTY_TEST.value,
            DetectorKind.FULL_SUITE.value,
        ),
        PropertyClass.PROOF_ADEQUACY.value: (
            DetectorKind.FORMAL_OBLIGATION.value,
            DetectorKind.INCREMENTAL_SEAL.value,
        ),
        PropertyClass.RECEIPT_AUTHENTICITY.value: (
            DetectorKind.INCREMENTAL_SEAL.value,
            DetectorKind.FORMAL_OBLIGATION.value,
            DetectorKind.STATIC_RULE.value,
        ),
        PropertyClass.CAPSULE_COMPLETENESS.value: (
            DetectorKind.FORMAL_OBLIGATION.value,
            DetectorKind.INCREMENTAL_SEAL.value,
            DetectorKind.STATIC_RULE.value,
        ),
        PropertyClass.GUI_ACTION_BINDING.value: (
            DetectorKind.UNIT_TEST.value,
            DetectorKind.INTEGRATION_TEST.value,
            DetectorKind.STATIC_RULE.value,
        ),
        PropertyClass.IDEMPOTENCY.value: (
            DetectorKind.PROPERTY_TEST.value,
            DetectorKind.UNIT_TEST.value,
            DetectorKind.INTEGRATION_TEST.value,
        ),
        PropertyClass.COMPENSATION.value: (
            DetectorKind.INTEGRATION_TEST.value,
            DetectorKind.PROPERTY_TEST.value,
            DetectorKind.UNIT_TEST.value,
        ),
        PropertyClass.CANCELLATION.value: (
            DetectorKind.UNIT_TEST.value,
            DetectorKind.PROPERTY_TEST.value,
            DetectorKind.RUNTIME_INVARIANT.value,
        ),
    }
)

_REQUIRED_PREDICTION_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "detector_identity",
        "detector_revision",
    }
)


class DetectionPredictionError(AssuranceBaseError):
    """Raised when expected-detection construction fails closed."""


class DependencyRelation(str, Enum):
    """Closed relation vocabulary for semantic dependency edges."""

    DEPENDS_ON = "depends_on"
    TESTED_BY = "tested_by"
    PROVED_BY = "proved_by"
    ENFORCED_BY = "enforced_by"
    OBSERVED_BY = "observed_by"
    SEALED_BY = "sealed_by"
    IMPLEMENTS = "implements"
    CALLS = "calls"
    IMPORTS = "imports"
    CONSTRAINS = "constrains"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise DetectionPredictionError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise DetectionPredictionError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise DetectionPredictionError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise DetectionPredictionError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise DetectionPredictionError(f"{name} must be a valid CID") from exc


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise DetectionPredictionError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name)
    if _VERSION_RE.fullmatch(text) is None:
        raise DetectionPredictionError(
            f"{name} must be a version token matching {_VERSION_RE.pattern}"
        )
    return text


def _repository_id(value: Any, name: str = "repository_id") -> str:
    text = _text(value, name)
    if _REPOSITORY_ID_RE.fullmatch(text) is None:
        raise DetectionPredictionError(
            f"{name} must be a repository identity matching "
            f"{_REPOSITORY_ID_RE.pattern}"
        )
    return text


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise DetectionPredictionError(f"{name} must be a boolean")
    return value


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise DetectionPredictionError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, f"{name}[]") for value in values))
    if len(ordered) > maximum:
        raise DetectionPredictionError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise DetectionPredictionError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_enums(
    values: Iterable[Any],
    enum_type: type[Enum],
    name: str,
    *,
    maximum: int = MAX_PROPERTY_CLASSES,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise DetectionPredictionError(f"{name} must be a list")
    ordered = tuple(sorted({_enum(value, enum_type, name) for value in values}))
    if len(ordered) > maximum:
        raise DetectionPredictionError(f"{name} exceeds maximum length")
    return ordered


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


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise DetectionPredictionError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_model_authority_and_host_fallbacks(thawed, path=name)
    except AssuranceBaseError as exc:
        raise DetectionPredictionError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise DetectionPredictionError(f"{name} must be a mapping")
    return _freeze_structured(_require_structured(dict(value), name))


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise DetectionPredictionError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise DetectionPredictionError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    missing = fields - set(data)
    # Optional fields may be absent on construction; identity payloads are closed.
    return dict(data)


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except AssuranceBaseError as exc:
            raise DetectionPredictionError(str(exc)) from exc
    raise DetectionPredictionError(f"{name} must be AssuranceArtifactHeader or mapping")


def _normalize_candidate(
    value: MutationCandidate | Mapping[str, Any],
    name: str = "mutation",
) -> MutationCandidate:
    if isinstance(value, MutationCandidate):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value or "candidate_cid" in value:
                return MutationCandidate.from_dict(value)
            return MutationCandidate(
                header=value["header"],
                candidate_id=value["candidate_id"],
                operator_id=value["operator_id"],
                operator_version=value["operator_version"],
                operator_cid=value["operator_cid"],
                target_id=value["target_id"],
                target_cid=value["target_cid"],
                seed_config=value["seed_config"],
                source_root_cid=value["source_root_cid"],
                repository_state_cid=value["repository_state_cid"],
                transformation_summary=value["transformation_summary"],
                expected_violated_property_classes=value[
                    "expected_violated_property_classes"
                ],
                risk_class=value["risk_class"],
                likely_equivalent=value["likely_equivalent"],
                scope_symbol_ids=value["scope_symbol_ids"],
                scope_paths=value.get("scope_paths", ()),
                notes=value.get("notes"),
                metadata=value.get("metadata", {}),
            )
        except (MutationContractError, AssuranceBaseError, KeyError, TypeError) as exc:
            raise DetectionPredictionError(
                f"{name} is not a sealed MutationCandidate: {exc}"
            ) from exc
    raise DetectionPredictionError(f"{name} must be MutationCandidate or mapping")


# ---------------------------------------------------------------------------
# Sealed input models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DetectorCatalogEntry:
    """One versioned detector admitted into the assurance manifest catalog.

    ``detector_id`` is the durable identity; ``detector_revision`` is the exact
    revision pin required by every prediction. Anchor IDs are semantic-graph
    nodes the detector observes (tests, proofs, policy rules, seals, ...).
    """

    detector_id: str
    detector_revision: str
    detector_kind: DetectorKind | str
    covered_property_classes: Sequence[PropertyClass | str]
    anchor_ids: Sequence[str]
    default_strength: DetectorStrength | str = DetectorStrength.REQUIRED
    expected_terminal_status: AssuranceTerminalStatus | str = (
        AssuranceTerminalStatus.COMPLETE
    )
    observation_template: str | None = None
    claim_ids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "detector_id",
            "detector_revision",
            "detector_kind",
            "covered_property_classes",
            "anchor_ids",
            "default_strength",
            "expected_terminal_status",
            "observation_template",
            "claim_ids",
            "notes",
            "metadata",
            "catalog_entry_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "detector_id", _token(self.detector_id, "detector_id")
        )
        object.__setattr__(
            self,
            "detector_revision",
            _version(self.detector_revision, "detector_revision"),
        )
        object.__setattr__(
            self,
            "detector_kind",
            _enum(self.detector_kind, DetectorKind, "detector_kind"),
        )
        properties = _unique_sorted_enums(
            list(self.covered_property_classes),
            PropertyClass,
            "covered_property_classes",
        )
        if not properties:
            raise DetectionPredictionError(
                "covered_property_classes must not be empty"
            )
        object.__setattr__(self, "covered_property_classes", properties)
        anchors = _unique_sorted_tokens(
            list(self.anchor_ids), "anchor_ids", maximum=MAX_ANCHORS
        )
        if not anchors:
            raise DetectionPredictionError("anchor_ids must not be empty")
        object.__setattr__(self, "anchor_ids", anchors)
        object.__setattr__(
            self,
            "default_strength",
            _enum(self.default_strength, DetectorStrength, "default_strength"),
        )
        object.__setattr__(
            self,
            "expected_terminal_status",
            _enum(
                self.expected_terminal_status,
                AssuranceTerminalStatus,
                "expected_terminal_status",
            ),
        )
        object.__setattr__(
            self,
            "observation_template",
            _optional_text(self.observation_template, "observation_template"),
        )
        object.__setattr__(
            self,
            "claim_ids",
            _unique_sorted_tokens(list(self.claim_ids), "claim_ids"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DETECTOR_CATALOG_ENTRY_SCHEMA,
            "detector_id": self.detector_id,
            "detector_revision": self.detector_revision,
            "detector_kind": self.detector_kind,
            "covered_property_classes": list(self.covered_property_classes),
            "anchor_ids": list(self.anchor_ids),
            "default_strength": self.default_strength,
            "expected_terminal_status": self.expected_terminal_status,
            "observation_template": self.observation_template,
            "claim_ids": list(self.claim_ids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def catalog_entry_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["catalog_entry_cid"] = self.catalog_entry_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DetectorCatalogEntry":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("catalog_entry_cid", None)
        schema = payload.pop("schema", DETECTOR_CATALOG_ENTRY_SCHEMA)
        if schema != DETECTOR_CATALOG_ENTRY_SCHEMA:
            raise DetectionPredictionError(
                "unsupported DetectorCatalogEntry schema version"
            )
        result = cls(
            detector_id=payload["detector_id"],
            detector_revision=payload["detector_revision"],
            detector_kind=payload["detector_kind"],
            covered_property_classes=payload["covered_property_classes"],
            anchor_ids=payload["anchor_ids"],
            default_strength=payload.get(
                "default_strength", DetectorStrength.REQUIRED.value
            ),
            expected_terminal_status=payload.get(
                "expected_terminal_status",
                AssuranceTerminalStatus.COMPLETE.value,
            ),
            observation_template=payload.get("observation_template"),
            claim_ids=payload.get("claim_ids", ()),
            notes=payload.get("notes"),
            metadata=payload.get("metadata", {}),
        )
        if claimed is not None and claimed != result.catalog_entry_cid:
            raise DetectionPredictionError(
                "DetectorCatalogEntry catalog_entry_cid identity mismatch"
            )
        return result

    @classmethod
    def normalize(
        cls, value: "DetectorCatalogEntry | Mapping[str, Any]"
    ) -> "DetectorCatalogEntry":
        if isinstance(value, DetectorCatalogEntry):
            return value
        if isinstance(value, Mapping):
            if "schema" in value or "catalog_entry_cid" in value:
                return cls.from_dict(value)
            return cls(
                detector_id=value["detector_id"],
                detector_revision=value["detector_revision"],
                detector_kind=value["detector_kind"],
                covered_property_classes=value["covered_property_classes"],
                anchor_ids=value["anchor_ids"],
                default_strength=value.get(
                    "default_strength", DetectorStrength.REQUIRED.value
                ),
                expected_terminal_status=value.get(
                    "expected_terminal_status",
                    AssuranceTerminalStatus.COMPLETE.value,
                ),
                observation_template=value.get("observation_template"),
                claim_ids=value.get("claim_ids", ()),
                notes=value.get("notes"),
                metadata=value.get("metadata", {}),
            )
        raise DetectionPredictionError(
            "detector must be DetectorCatalogEntry or mapping"
        )


@dataclass(frozen=True, slots=True)
class SemanticDependencyEdge:
    """One directed semantic-dependency edge connecting mutation scope to detectors."""

    from_id: str
    to_id: str
    relation: DependencyRelation | str
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "from_id",
            "to_id",
            "relation",
            "notes",
            "edge_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "from_id", _token(self.from_id, "from_id"))
        object.__setattr__(self, "to_id", _token(self.to_id, "to_id"))
        if self.from_id == self.to_id:
            raise DetectionPredictionError("dependency edge must not be a self-loop")
        object.__setattr__(
            self, "relation", _enum(self.relation, DependencyRelation, "relation")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SEMANTIC_DEPENDENCY_EDGE_SCHEMA,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "relation": self.relation,
            "notes": self.notes,
        }

    @property
    def edge_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["edge_cid"] = self.edge_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticDependencyEdge":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("edge_cid", None)
        schema = payload.pop("schema", SEMANTIC_DEPENDENCY_EDGE_SCHEMA)
        if schema != SEMANTIC_DEPENDENCY_EDGE_SCHEMA:
            raise DetectionPredictionError(
                "unsupported SemanticDependencyEdge schema version"
            )
        result = cls(
            from_id=payload["from_id"],
            to_id=payload["to_id"],
            relation=payload["relation"],
            notes=payload.get("notes"),
        )
        if claimed is not None and claimed != result.edge_cid:
            raise DetectionPredictionError(
                "SemanticDependencyEdge edge_cid identity mismatch"
            )
        return result

    @classmethod
    def normalize(
        cls, value: "SemanticDependencyEdge | Mapping[str, Any]"
    ) -> "SemanticDependencyEdge":
        if isinstance(value, SemanticDependencyEdge):
            return value
        if isinstance(value, Mapping):
            if "schema" in value or "edge_cid" in value:
                return cls.from_dict(value)
            return cls(
                from_id=value["from_id"],
                to_id=value["to_id"],
                relation=value["relation"],
                notes=value.get("notes"),
            )
        raise DetectionPredictionError(
            "dependency edge must be SemanticDependencyEdge or mapping"
        )


@dataclass(frozen=True, slots=True)
class ClaimBinding:
    """A violated-claim statement bound to property classes and symbols."""

    claim_id: str
    property_class: PropertyClass | str
    statement: str
    symbol_ids: Sequence[str]
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "claim_id",
            "property_class",
            "statement",
            "symbol_ids",
            "notes",
            "metadata",
            "claim_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _token(self.claim_id, "claim_id"))
        object.__setattr__(
            self,
            "property_class",
            _enum(self.property_class, PropertyClass, "property_class"),
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        symbols = _unique_sorted_tokens(
            list(self.symbol_ids), "symbol_ids", maximum=MAX_ANCHORS
        )
        if not symbols:
            raise DetectionPredictionError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CLAIM_BINDING_SCHEMA,
            "claim_id": self.claim_id,
            "property_class": self.property_class,
            "statement": self.statement,
            "symbol_ids": list(self.symbol_ids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def claim_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["claim_cid"] = self.claim_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClaimBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("claim_cid", None)
        schema = payload.pop("schema", CLAIM_BINDING_SCHEMA)
        if schema != CLAIM_BINDING_SCHEMA:
            raise DetectionPredictionError(
                "unsupported ClaimBinding schema version"
            )
        result = cls(
            claim_id=payload["claim_id"],
            property_class=payload["property_class"],
            statement=payload["statement"],
            symbol_ids=payload["symbol_ids"],
            notes=payload.get("notes"),
            metadata=payload.get("metadata", {}),
        )
        if claimed is not None and claimed != result.claim_cid:
            raise DetectionPredictionError(
                "ClaimBinding claim_cid identity mismatch"
            )
        return result

    @classmethod
    def normalize(cls, value: "ClaimBinding | Mapping[str, Any]") -> "ClaimBinding":
        if isinstance(value, ClaimBinding):
            return value
        if isinstance(value, Mapping):
            if "schema" in value or "claim_cid" in value:
                return cls.from_dict(value)
            return cls(
                claim_id=value["claim_id"],
                property_class=value["property_class"],
                statement=value["statement"],
                symbol_ids=value["symbol_ids"],
                notes=value.get("notes"),
                metadata=value.get("metadata", {}),
            )
        raise DetectionPredictionError(
            "claim must be ClaimBinding or mapping"
        )


@dataclass(frozen=True, slots=True)
class DetectionAssuranceManifest:
    """Assurance-manifest slice used by ``predict_detection_set@1``.

    Binds the repository state under analysis, claim statements, the detector
    catalog with exact identity/revision pins, and the semantic-dependency
    edges connecting mutation scope symbols to detector anchors.
    """

    repository_id: str
    repository_state_cid: str
    detectors: Sequence[DetectorCatalogEntry | Mapping[str, Any]]
    dependency_edges: Sequence[SemanticDependencyEdge | Mapping[str, Any]]
    claims: Sequence[ClaimBinding | Mapping[str, Any]] = ()
    enable_type_check_fallback: bool = True
    enable_full_suite_fallback: bool = True
    enable_incremental_seal_fallback: bool = True
    enable_human_review_fallback: bool = True
    observation_complete: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "repository_id",
            "repository_state_cid",
            "detectors",
            "dependency_edges",
            "claims",
            "enable_type_check_fallback",
            "enable_full_suite_fallback",
            "enable_incremental_seal_fallback",
            "enable_human_review_fallback",
            "observation_complete",
            "notes",
            "metadata",
            "manifest_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "repository_id", _repository_id(self.repository_id, "repository_id")
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _cid(self.repository_state_cid, "repository_state_cid"),
        )
        if not isinstance(self.detectors, (list, tuple)):
            raise DetectionPredictionError("detectors must be a list")
        if len(self.detectors) > MAX_DETECTORS:
            raise DetectionPredictionError("detectors exceeds maximum length")
        sealed_detectors = tuple(
            DetectorCatalogEntry.normalize(item) for item in self.detectors
        )
        detector_ids = [item.detector_id for item in sealed_detectors]
        if len(detector_ids) != len(set(detector_ids)):
            raise DetectionPredictionError("detectors detector_id values must be unique")
        object.__setattr__(
            self,
            "detectors",
            tuple(sorted(sealed_detectors, key=lambda item: item.detector_id)),
        )

        if not isinstance(self.dependency_edges, (list, tuple)):
            raise DetectionPredictionError("dependency_edges must be a list")
        if len(self.dependency_edges) > MAX_EDGES:
            raise DetectionPredictionError("dependency_edges exceeds maximum length")
        sealed_edges = tuple(
            SemanticDependencyEdge.normalize(item) for item in self.dependency_edges
        )
        edge_keys = {(item.from_id, item.to_id, item.relation) for item in sealed_edges}
        if len(edge_keys) != len(sealed_edges):
            raise DetectionPredictionError(
                "dependency_edges must be unique by (from_id, to_id, relation)"
            )
        object.__setattr__(
            self,
            "dependency_edges",
            tuple(
                sorted(
                    sealed_edges,
                    key=lambda item: (item.from_id, item.to_id, item.relation),
                )
            ),
        )

        if not isinstance(self.claims, (list, tuple)):
            raise DetectionPredictionError("claims must be a list")
        if len(self.claims) > MAX_CLAIMS:
            raise DetectionPredictionError("claims exceeds maximum length")
        sealed_claims = tuple(ClaimBinding.normalize(item) for item in self.claims)
        claim_ids = [item.claim_id for item in sealed_claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise DetectionPredictionError("claims claim_id values must be unique")
        object.__setattr__(
            self,
            "claims",
            tuple(sorted(sealed_claims, key=lambda item: item.claim_id)),
        )

        object.__setattr__(
            self,
            "enable_type_check_fallback",
            _bool(self.enable_type_check_fallback, "enable_type_check_fallback"),
        )
        object.__setattr__(
            self,
            "enable_full_suite_fallback",
            _bool(self.enable_full_suite_fallback, "enable_full_suite_fallback"),
        )
        object.__setattr__(
            self,
            "enable_incremental_seal_fallback",
            _bool(
                self.enable_incremental_seal_fallback,
                "enable_incremental_seal_fallback",
            ),
        )
        object.__setattr__(
            self,
            "enable_human_review_fallback",
            _bool(self.enable_human_review_fallback, "enable_human_review_fallback"),
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
            "schema": DETECTION_ASSURANCE_MANIFEST_SCHEMA,
            "interface_id": DETECTION_ASSURANCE_MANIFEST_INTERFACE,
            "repository_id": self.repository_id,
            "repository_state_cid": self.repository_state_cid,
            "detectors": [item.identity_payload() for item in self.detectors],
            "dependency_edges": [
                item.identity_payload() for item in self.dependency_edges
            ],
            "claims": [item.identity_payload() for item in self.claims],
            "enable_type_check_fallback": self.enable_type_check_fallback,
            "enable_full_suite_fallback": self.enable_full_suite_fallback,
            "enable_incremental_seal_fallback": self.enable_incremental_seal_fallback,
            "enable_human_review_fallback": self.enable_human_review_fallback,
            "observation_complete": self.observation_complete,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def manifest_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["manifest_cid"] = self.manifest_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DetectionAssuranceManifest":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("manifest_cid", None)
        schema = payload.pop("schema", DETECTION_ASSURANCE_MANIFEST_SCHEMA)
        if schema != DETECTION_ASSURANCE_MANIFEST_SCHEMA:
            raise DetectionPredictionError(
                "unsupported DetectionAssuranceManifest schema version"
            )
        interface_id = payload.pop(
            "interface_id", DETECTION_ASSURANCE_MANIFEST_INTERFACE
        )
        if interface_id != DETECTION_ASSURANCE_MANIFEST_INTERFACE:
            raise DetectionPredictionError(
                "unsupported DetectionAssuranceManifest interface_id"
            )
        result = cls(
            repository_id=payload["repository_id"],
            repository_state_cid=payload["repository_state_cid"],
            detectors=payload["detectors"],
            dependency_edges=payload["dependency_edges"],
            claims=payload.get("claims", ()),
            enable_type_check_fallback=payload.get(
                "enable_type_check_fallback", True
            ),
            enable_full_suite_fallback=payload.get(
                "enable_full_suite_fallback", True
            ),
            enable_incremental_seal_fallback=payload.get(
                "enable_incremental_seal_fallback", True
            ),
            enable_human_review_fallback=payload.get(
                "enable_human_review_fallback", True
            ),
            observation_complete=payload.get("observation_complete", True),
            notes=payload.get("notes"),
            metadata=payload.get("metadata", {}),
        )
        if claimed is not None and claimed != result.manifest_cid:
            raise DetectionPredictionError(
                "DetectionAssuranceManifest manifest_cid identity mismatch"
            )
        return result

    @classmethod
    def normalize(
        cls, value: "DetectionAssuranceManifest | Mapping[str, Any]"
    ) -> "DetectionAssuranceManifest":
        if isinstance(value, DetectionAssuranceManifest):
            return value
        if isinstance(value, Mapping):
            if "schema" in value or "manifest_cid" in value:
                return cls.from_dict(value)
            return cls(
                repository_id=value["repository_id"],
                repository_state_cid=value["repository_state_cid"],
                detectors=value.get("detectors", ()),
                dependency_edges=value.get("dependency_edges", ()),
                claims=value.get("claims", ()),
                enable_type_check_fallback=value.get(
                    "enable_type_check_fallback", True
                ),
                enable_full_suite_fallback=value.get(
                    "enable_full_suite_fallback", True
                ),
                enable_incremental_seal_fallback=value.get(
                    "enable_incremental_seal_fallback", True
                ),
                enable_human_review_fallback=value.get(
                    "enable_human_review_fallback", True
                ),
                observation_complete=value.get("observation_complete", True),
                notes=value.get("notes"),
                metadata=value.get("metadata", {}),
            )
        raise DetectionPredictionError(
            "assurance_manifest must be DetectionAssuranceManifest or mapping"
        )


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


def _adjacency(
    edges: Sequence[SemanticDependencyEdge],
) -> Mapping[str, tuple[tuple[str, str], ...]]:
    """Undirected adjacency map: node -> ((neighbor, relation), ...)."""

    buckets: dict[str, list[tuple[str, str]]] = {}
    for edge in edges:
        buckets.setdefault(edge.from_id, []).append((edge.to_id, edge.relation))
        buckets.setdefault(edge.to_id, []).append((edge.from_id, edge.relation))
    return MappingProxyType(
        {
            node: tuple(sorted(set(neighbors), key=lambda item: item[0]))
            for node, neighbors in buckets.items()
        }
    )


def _shortest_dependency_path(
    *,
    sources: Sequence[str],
    targets: Sequence[str],
    adjacency: Mapping[str, tuple[tuple[str, str], ...]],
) -> tuple[str, ...] | None:
    """Return sorted unique path nodes from any source to any target, or None."""

    target_set = set(targets)
    if not sources or not target_set:
        return None
    # Direct hit: a source is also an anchor.
    direct = sorted(set(sources) & target_set)
    if direct:
        return tuple(direct)

    visited: set[str] = set()
    parent: dict[str, str | None] = {}
    queue: deque[str] = deque()
    for source in sorted(set(sources)):
        if source in visited:
            continue
        visited.add(source)
        parent[source] = None
        queue.append(source)

    found: str | None = None
    while queue:
        if len(visited) > MAX_PATH_SEARCH_NODES:
            raise DetectionPredictionError(
                "semantic dependency path search exceeds maximum nodes"
            )
        current = queue.popleft()
        if current in target_set:
            found = current
            break
        for neighbor, _relation in adjacency.get(current, ()):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            parent[neighbor] = current
            queue.append(neighbor)

    if found is None:
        return None

    chain: list[str] = []
    cursor: str | None = found
    while cursor is not None:
        chain.append(cursor)
        cursor = parent.get(cursor)
    # DetectorPrediction.dependency_path is unique-sorted tokens.
    return tuple(sorted(set(chain)))


def _scope_tokens(mutation: MutationCandidate) -> tuple[str, ...]:
    """Normalize mutation scope symbols to dependency tokens (fail closed)."""

    tokens: list[str] = []
    for symbol in mutation.scope_symbol_ids:
        try:
            tokens.append(_token(symbol, "scope_symbol_ids[]"))
        except DetectionPredictionError as exc:
            raise DetectionPredictionError(
                f"mutation scope_symbol_ids entry {symbol!r} is not a valid "
                f"dependency token required for detection prediction: {exc}"
            ) from exc
    if not tokens:
        raise DetectionPredictionError("mutation scope_symbol_ids must not be empty")
    return tuple(sorted(set(tokens)))


def _claims_for_property(
    claims: Sequence[ClaimBinding],
    property_class: str,
    scope: Sequence[str],
) -> tuple[ClaimBinding, ...]:
    scope_set = set(scope)
    matched = [
        claim
        for claim in claims
        if claim.property_class == property_class
        and set(claim.symbol_ids) & scope_set
    ]
    return tuple(sorted(matched, key=lambda item: item.claim_id))


def _synthesized_claim(
    *,
    property_class: str,
    mutation: MutationCandidate,
) -> str:
    return (
        f"{property_class} must remain intact under mutation "
        f"{mutation.candidate_id}: {mutation.transformation_summary}"
    )


def _observation_rationale(
    *,
    detector: DetectorCatalogEntry,
    property_class: str,
    claim_statement: str,
    dependency_path: Sequence[str],
    mutation: MutationCandidate,
) -> str:
    if detector.observation_template:
        template = detector.observation_template
        return (
            f"{template}; property={property_class}; claim={claim_statement}; "
            f"path={','.join(dependency_path)}; "
            f"mutation={mutation.transformation_summary}"
        )
    kind = detector.detector_kind
    return (
        f"{kind} detector {detector.detector_id}@{detector.detector_revision} "
        f"should observe violated {property_class} claim because semantic "
        f"dependencies connect mutated symbols to detector anchors via "
        f"[{', '.join(dependency_path)}]; claim: {claim_statement}; "
        f"mutation: {mutation.transformation_summary}"
    )


def _prediction_strength(
    *,
    detector: DetectorCatalogEntry,
    mutation: MutationCandidate,
    synthetic: bool,
) -> str:
    if mutation.likely_equivalent:
        return DetectorStrength.OPTIONAL.value
    if synthetic and detector.detector_kind in {
        DetectorKind.FULL_SUITE.value,
        DetectorKind.HUMAN_REVIEW.value,
    }:
        return DetectorStrength.OPTIONAL.value
    return str(detector.default_strength)


def _prediction_terminal_status(
    *,
    detector: DetectorCatalogEntry,
    mutation: MutationCandidate,
) -> str:
    if mutation.likely_equivalent and detector.detector_kind == (
        DetectorKind.HUMAN_REVIEW.value
    ):
        return AssuranceTerminalStatus.HUMAN_REVIEW_REQUIRED.value
    return str(detector.expected_terminal_status)


def _build_prediction(
    *,
    detector: DetectorCatalogEntry,
    property_class: str,
    claim_id: str | None,
    claim_statement: str,
    dependency_path: Sequence[str],
    mutation: MutationCandidate,
    synthetic: bool = False,
) -> DetectorPrediction:
    if not dependency_path:
        raise DetectionPredictionError("dependency_path must not be empty")
    if len(dependency_path) > MAX_DEPENDENCY_PATH:
        raise DetectionPredictionError("dependency_path exceeds maximum length")

    strength = _prediction_strength(
        detector=detector, mutation=mutation, synthetic=synthetic
    )
    terminal = _prediction_terminal_status(detector=detector, mutation=mutation)
    rationale = _observation_rationale(
        detector=detector,
        property_class=property_class,
        claim_statement=claim_statement,
        dependency_path=dependency_path,
        mutation=mutation,
    )
    metadata: dict[str, Any] = {
        "detector_identity": detector.detector_id,
        "detector_revision": detector.detector_revision,
        "catalog_entry_cid": detector.catalog_entry_cid,
        "property_class": property_class,
        "synthetic": synthetic,
        "operator_id": mutation.operator_id,
        "operator_version": mutation.operator_version,
    }
    if claim_id is not None:
        metadata["claim_id"] = claim_id
    if detector.notes is not None:
        metadata["catalog_notes"] = detector.notes

    try:
        prediction = DetectorPrediction(
            detector_id=detector.detector_id,
            detector_kind=detector.detector_kind,
            violated_claim=claim_statement,
            observation_rationale=rationale,
            dependency_path=tuple(dependency_path),
            strength=strength,
            expected_terminal_status=terminal,
            notes=detector.notes,
            metadata=metadata,
        )
    except ExecutionContractError as exc:
        raise DetectionPredictionError(
            f"failed to seal DetectorPrediction for {detector.detector_id!r}: {exc}"
        ) from exc
    _assert_prediction_explained(prediction)
    return prediction


def _assert_prediction_explained(prediction: DetectorPrediction) -> None:
    """Fail closed when a prediction omits any required explanation field."""

    if not prediction.violated_claim:
        raise DetectionPredictionError("prediction missing violated_claim")
    if not prediction.observation_rationale:
        raise DetectionPredictionError("prediction missing observation_rationale")
    if not prediction.dependency_path:
        raise DetectionPredictionError("prediction missing dependency_path")
    if prediction.strength not in {
        DetectorStrength.REQUIRED.value,
        DetectorStrength.OPTIONAL.value,
    }:
        raise DetectionPredictionError("prediction missing required/optional strength")
    if not prediction.expected_terminal_status:
        raise DetectionPredictionError("prediction missing expected_terminal_status")
    if not prediction.detector_id:
        raise DetectionPredictionError("prediction missing detector identity")
    metadata = dict(prediction.metadata)
    missing = sorted(_REQUIRED_PREDICTION_METADATA_KEYS - set(metadata))
    if missing:
        raise DetectionPredictionError(
            "prediction missing exact detector identity/revision metadata: "
            + ", ".join(missing)
        )
    if metadata.get("detector_identity") != prediction.detector_id:
        raise DetectionPredictionError(
            "prediction detector_identity metadata must match detector_id"
        )
    revision = metadata.get("detector_revision")
    if type(revision) is not str or not revision:
        raise DetectionPredictionError(
            "prediction missing exact detector_revision"
        )
    if _VERSION_RE.fullmatch(revision) is None:
        raise DetectionPredictionError(
            f"prediction detector_revision is not a version token: {revision!r}"
        )


def _synthetic_entry(
    *,
    detector_id: str,
    detector_revision: str,
    detector_kind: DetectorKind,
    property_classes: Sequence[str],
    anchor_ids: Sequence[str],
    strength: DetectorStrength,
    terminal: AssuranceTerminalStatus,
    observation_template: str,
) -> DetectorCatalogEntry:
    return DetectorCatalogEntry(
        detector_id=detector_id,
        detector_revision=detector_revision,
        detector_kind=detector_kind,
        covered_property_classes=tuple(property_classes),
        anchor_ids=tuple(anchor_ids),
        default_strength=strength,
        expected_terminal_status=terminal,
        observation_template=observation_template,
    )


def _stable_detection_set_id(candidate_id: str) -> str:
    digest = blake2b(
        f"expected_detection_set\0{candidate_id}".encode("utf-8"),
        digest_size=8,
    ).hexdigest()
    return f"eds_{digest}"


def _detection_set_header(
    mutation: MutationCandidate,
    *,
    symbols: Sequence[str],
) -> AssuranceArtifactHeader:
    base = mutation.header
    generator = GeneratorIdentity(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=PREDICT_DETECTION_SET_INTERFACE,
    )
    versions = VersionBinding(
        operator_id=mutation.operator_id,
        operator_version=mutation.operator_version,
        campaign_policy_id=base.versions.campaign_policy_id,
        campaign_policy_version=base.versions.campaign_policy_version,
        generator=generator,
    )
    # Provenance is deterministic construction, not observed execution.
    provenance = ArtifactProvenance(
        producer_id=base.provenance.producer_id,
        producer_version=base.provenance.producer_version,
        execution_mode=ExecutionMode.LIVE
        if base.provenance.execution_mode != ExecutionMode.SIMULATED.value
        else ExecutionMode.SIMULATED,
        authority_source=AuthoritySource.DETERMINISTIC,
        input_cids=tuple(
            sorted(
                {
                    *base.provenance.input_cids,
                    mutation.candidate_cid,
                }
            )
        ),
        tool_ids=tuple(
            sorted({*base.provenance.tool_ids, "predict_detection_set.v1"})
        ),
        policy_cid=base.provenance.policy_cid,
        notes="expected detection set constructed from semantic dependencies",
    )
    terminal = base.terminal_status
    if provenance.execution_mode == ExecutionMode.SIMULATED.value:
        terminal = AssuranceTerminalStatus.SIMULATED.value
    return AssuranceArtifactHeader(
        artifact_kind="expected_detection_set",
        repository_id=base.repository_id,
        repository_state_cid=mutation.repository_state_cid,
        target_symbol_ids=tuple(symbols) if symbols else tuple(base.target_symbol_ids),
        target_artifact_cids=tuple(base.target_artifact_cids),
        capsule_cids=tuple(base.capsule_cids),
        proof_unit_cids=tuple(base.proof_unit_cids),
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        versions=versions,
        provenance=provenance,
        terminal_status=terminal,
        receipt_cids=tuple(base.receipt_cids),
        proof_cids=tuple(base.proof_cids),
        metadata={
            **_thaw_structured(base.metadata),
            "candidate_id": mutation.candidate_id,
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
        },
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def preferred_detector_kinds_for_property(
    property_class: PropertyClass | str,
) -> tuple[str, ...]:
    """Return preferred detector kinds for a closed property class."""

    key = _enum(property_class, PropertyClass, "property_class")
    kinds = PROPERTY_CLASS_DETECTOR_KINDS.get(key)
    if kinds is None:
        raise DetectionPredictionError(
            f"property_class {key!r} has no detector-kind mapping"
        )
    return kinds


def dependency_relations() -> tuple[str, ...]:
    """Return the closed dependency-relation vocabulary."""

    return tuple(item.value for item in DependencyRelation)


def assert_prediction_explained(
    prediction: DetectorPrediction | Mapping[str, Any],
) -> DetectorPrediction:
    """Public fail-closed check that a prediction is fully explained."""

    if isinstance(prediction, Mapping):
        try:
            sealed = DetectorPrediction.from_dict(prediction)
        except ExecutionContractError as exc:
            raise DetectionPredictionError(str(exc)) from exc
    elif isinstance(prediction, DetectorPrediction):
        sealed = prediction
    else:
        raise DetectionPredictionError(
            "prediction must be DetectorPrediction or mapping"
        )
    _assert_prediction_explained(sealed)
    return sealed


def predict_detection_set(
    mutation: MutationCandidate | Mapping[str, Any],
    assurance_manifest: DetectionAssuranceManifest | Mapping[str, Any],
    *,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ExpectedDetectionSet:
    """Construct an explained expected detection set for one mutation.

    Interface: ``predict_detection_set@1``

    Walks semantic dependencies from the mutation's scope symbols to catalog
    detectors that cover the mutation's expected violated property classes.
    Every emitted prediction names the violated claim, observation rationale,
    dependency path, required/optional strength, expected terminal status, and
    exact detector identity/revision.

    Fail-closed when:

    * observation is incomplete;
    * repository identity/state disagree between mutation and manifest;
    * no detector (catalog or synthetic fallback) can be bound with a path;
    * any emitted prediction is incomplete.
    """

    sealed_mutation = _normalize_candidate(mutation, "mutation")
    sealed_manifest = DetectionAssuranceManifest.normalize(assurance_manifest)

    if not sealed_manifest.observation_complete:
        raise DetectionPredictionError(
            "predict_detection_set fails closed when observation_complete is false"
        )

    if sealed_mutation.header.repository_id != sealed_manifest.repository_id:
        raise DetectionPredictionError(
            "mutation repository_id must match assurance_manifest.repository_id"
        )
    if sealed_mutation.repository_state_cid != sealed_manifest.repository_state_cid:
        raise DetectionPredictionError(
            "mutation repository_state_cid must match "
            "assurance_manifest.repository_state_cid"
        )
    if (
        sealed_mutation.header.repository_state_cid
        != sealed_manifest.repository_state_cid
    ):
        raise DetectionPredictionError(
            "mutation header.repository_state_cid must match "
            "assurance_manifest.repository_state_cid"
        )

    scope = _scope_tokens(sealed_mutation)
    adjacency = _adjacency(sealed_manifest.dependency_edges)
    violated = tuple(sealed_mutation.expected_violated_property_classes)
    if not violated:
        raise DetectionPredictionError(
            "mutation expected_violated_property_classes must not be empty"
        )

    predictions_by_id: dict[str, DetectorPrediction] = {}

    def _register(prediction: DetectorPrediction) -> None:
        existing = predictions_by_id.get(prediction.detector_id)
        if existing is None:
            predictions_by_id[prediction.detector_id] = prediction
            return
        # Prefer required over optional; otherwise keep lexicographically first
        # rationale for determinism (already sealed predictions are equal on id).
        if (
            existing.strength == DetectorStrength.OPTIONAL.value
            and prediction.strength == DetectorStrength.REQUIRED.value
        ):
            predictions_by_id[prediction.detector_id] = prediction

    # --- catalog detectors reachable via semantic dependencies ---
    for property_class in violated:
        preferred = set(preferred_detector_kinds_for_property(property_class))
        matched_claims = _claims_for_property(
            sealed_manifest.claims, property_class, scope
        )
        claim_statement = (
            matched_claims[0].statement
            if matched_claims
            else _synthesized_claim(
                property_class=property_class, mutation=sealed_mutation
            )
        )
        claim_id = matched_claims[0].claim_id if matched_claims else None
        matched_claim_ids = {item.claim_id for item in matched_claims}

        for detector in sealed_manifest.detectors:
            if property_class not in detector.covered_property_classes:
                continue
            # Prefer detectors whose kind maps to the property, but do not drop
            # explicitly claim-bound detectors even if kind is broader.
            claim_bound = bool(detector.claim_ids) and bool(
                set(detector.claim_ids) & matched_claim_ids
            )
            if detector.detector_kind not in preferred and not claim_bound:
                # Still admit when the detector covers the property class; the
                # preferred set is guidance, not a hard filter.
                pass

            path = _shortest_dependency_path(
                sources=scope,
                targets=detector.anchor_ids,
                adjacency=adjacency,
            )
            if path is None:
                continue

            # If the detector declares claim_ids, require intersection when
            # matching claims exist for this property.
            if detector.claim_ids and matched_claim_ids:
                if not set(detector.claim_ids) & matched_claim_ids:
                    continue
                # Prefer the first intersecting claim statement.
                for claim in matched_claims:
                    if claim.claim_id in detector.claim_ids:
                        claim_statement = claim.statement
                        claim_id = claim.claim_id
                        break

            _register(
                _build_prediction(
                    detector=detector,
                    property_class=property_class,
                    claim_id=claim_id,
                    claim_statement=claim_statement,
                    dependency_path=path,
                    mutation=sealed_mutation,
                    synthetic=False,
                )
            )

    # --- synthetic structural fallbacks ---
    primary_claim = (
        sealed_manifest.claims[0].statement
        if sealed_manifest.claims
        else _synthesized_claim(
            property_class=violated[0], mutation=sealed_mutation
        )
    )
    primary_claim_id = (
        sealed_manifest.claims[0].claim_id if sealed_manifest.claims else None
    )
    primary_path = tuple(scope)

    needs_type = sealed_manifest.enable_type_check_fallback and bool(
        set(violated) & _TYPE_CHECK_PROPERTY_CLASSES
    )
    if needs_type and SYNTHETIC_TYPE_CHECK_ID not in predictions_by_id:
        type_detector = _synthetic_entry(
            detector_id=SYNTHETIC_TYPE_CHECK_ID,
            detector_revision=SYNTHETIC_TYPE_CHECK_REVISION,
            detector_kind=DetectorKind.TYPE_CHECK,
            property_classes=sorted(set(violated) & _TYPE_CHECK_PROPERTY_CLASSES)
            or list(violated),
            anchor_ids=scope,
            strength=DetectorStrength.REQUIRED,
            terminal=AssuranceTerminalStatus.COMPLETE,
            observation_template=(
                "type check should reject schema/interface/data integrity drift"
            ),
        )
        _register(
            _build_prediction(
                detector=type_detector,
                property_class=next(
                    prop for prop in violated if prop in _TYPE_CHECK_PROPERTY_CLASSES
                )
                if set(violated) & _TYPE_CHECK_PROPERTY_CLASSES
                else violated[0],
                claim_id=primary_claim_id,
                claim_statement=primary_claim,
                dependency_path=primary_path,
                mutation=sealed_mutation,
                synthetic=True,
            )
        )

    needs_seal = sealed_manifest.enable_incremental_seal_fallback and bool(
        set(violated) & _FORMAL_PROPERTY_CLASSES
    )
    if needs_seal and SYNTHETIC_SEAL_ID not in predictions_by_id:
        seal_detector = _synthetic_entry(
            detector_id=SYNTHETIC_SEAL_ID,
            detector_revision=SYNTHETIC_SEAL_REVISION,
            detector_kind=DetectorKind.INCREMENTAL_SEAL,
            property_classes=sorted(set(violated) & _FORMAL_PROPERTY_CLASSES)
            or list(violated),
            anchor_ids=scope,
            strength=DetectorStrength.REQUIRED,
            terminal=AssuranceTerminalStatus.COMPLETE,
            observation_template=(
                "incremental seal verification should fail when proof/receipt "
                "adequacy is violated"
            ),
        )
        _register(
            _build_prediction(
                detector=seal_detector,
                property_class=next(
                    prop for prop in violated if prop in _FORMAL_PROPERTY_CLASSES
                )
                if set(violated) & _FORMAL_PROPERTY_CLASSES
                else violated[0],
                claim_id=primary_claim_id,
                claim_statement=primary_claim,
                dependency_path=primary_path,
                mutation=sealed_mutation,
                synthetic=True,
            )
        )

    high_risk = sealed_mutation.risk_class in _HIGH_RISK_CLASSES
    if (
        sealed_manifest.enable_full_suite_fallback
        and high_risk
        and SYNTHETIC_FULL_SUITE_ID not in predictions_by_id
    ):
        suite_detector = _synthetic_entry(
            detector_id=SYNTHETIC_FULL_SUITE_ID,
            detector_revision=SYNTHETIC_FULL_SUITE_REVISION,
            detector_kind=DetectorKind.FULL_SUITE,
            property_classes=list(violated),
            anchor_ids=scope,
            strength=DetectorStrength.OPTIONAL,
            terminal=AssuranceTerminalStatus.COMPLETE,
            observation_template=(
                "full-suite fallback may observe the violation when selected "
                "incremental detectors miss it"
            ),
        )
        _register(
            _build_prediction(
                detector=suite_detector,
                property_class=violated[0],
                claim_id=primary_claim_id,
                claim_statement=primary_claim,
                dependency_path=primary_path,
                mutation=sealed_mutation,
                synthetic=True,
            )
        )

    if (
        sealed_manifest.enable_human_review_fallback
        and (high_risk or sealed_mutation.likely_equivalent)
        and SYNTHETIC_HUMAN_REVIEW_ID not in predictions_by_id
    ):
        human_detector = _synthetic_entry(
            detector_id=SYNTHETIC_HUMAN_REVIEW_ID,
            detector_revision=SYNTHETIC_HUMAN_REVIEW_REVISION,
            detector_kind=DetectorKind.HUMAN_REVIEW,
            property_classes=list(violated),
            anchor_ids=scope,
            strength=DetectorStrength.OPTIONAL,
            terminal=(
                AssuranceTerminalStatus.HUMAN_REVIEW_REQUIRED
                if sealed_mutation.likely_equivalent
                else AssuranceTerminalStatus.COMPLETE
            ),
            observation_template=(
                "human review is predicted when risk is high or equivalence "
                "is unresolved"
            ),
        )
        _register(
            _build_prediction(
                detector=human_detector,
                property_class=violated[0],
                claim_id=primary_claim_id,
                claim_statement=primary_claim,
                dependency_path=primary_path,
                mutation=sealed_mutation,
                synthetic=True,
            )
        )

    if not predictions_by_id:
        raise DetectionPredictionError(
            "no detectors reachable via semantic dependencies for the mutation's "
            "violated property classes; refuse empty expected detection set"
        )

    predictions = tuple(
        sorted(predictions_by_id.values(), key=lambda item: item.detector_id)
    )
    for prediction in predictions:
        _assert_prediction_explained(prediction)

    header = _detection_set_header(sealed_mutation, symbols=scope)
    result_metadata: dict[str, Any] = {
        "manifest_cid": sealed_manifest.manifest_cid,
        "candidate_cid": sealed_mutation.candidate_cid,
        "interface_id": PREDICT_DETECTION_SET_INTERFACE,
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "predicted_count": len(predictions),
        "violated_property_classes": list(violated),
    }
    if metadata:
        result_metadata.update(_thaw_structured(_mapping(metadata, "metadata")))

    try:
        detection_set = ExpectedDetectionSet(
            header=header,
            detection_set_id=_stable_detection_set_id(sealed_mutation.candidate_id),
            candidate_id=sealed_mutation.candidate_id,
            candidate_cid=sealed_mutation.candidate_cid,
            predicted_detectors=predictions,
            notes=_optional_text(notes, "notes") if notes is not None else None,
            metadata=result_metadata,
        )
    except ExecutionContractError as exc:
        raise DetectionPredictionError(
            f"failed to seal ExpectedDetectionSet: {exc}"
        ) from exc

    verify_detection_set_identity(detection_set)
    return detection_set


__all__ = [
    "CLAIM_BINDING_SCHEMA",
    "DETECTION_ASSURANCE_MANIFEST_INTERFACE",
    "DETECTION_ASSURANCE_MANIFEST_SCHEMA",
    "DETECTOR_CATALOG_ENTRY_SCHEMA",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "PREDICT_DETECTION_SET_INTERFACE",
    "PROPERTY_CLASS_DETECTOR_KINDS",
    "SEMANTIC_DEPENDENCY_EDGE_SCHEMA",
    "SYNTHETIC_FULL_SUITE_ID",
    "SYNTHETIC_FULL_SUITE_REVISION",
    "SYNTHETIC_HUMAN_REVIEW_ID",
    "SYNTHETIC_HUMAN_REVIEW_REVISION",
    "SYNTHETIC_SEAL_ID",
    "SYNTHETIC_SEAL_REVISION",
    "SYNTHETIC_TYPE_CHECK_ID",
    "SYNTHETIC_TYPE_CHECK_REVISION",
    "ClaimBinding",
    "DependencyRelation",
    "DetectionAssuranceManifest",
    "DetectionPredictionError",
    "DetectorCatalogEntry",
    "SemanticDependencyEdge",
    "assert_prediction_explained",
    "dependency_relations",
    "predict_detection_set",
    "preferred_detector_kinds_for_property",
]
