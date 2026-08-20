"""Canonical semantic-governor artifact base: statuses, provenance, identity.

This module exclusively owns the closed, versioned common header and shared
enums used by every durable semantic-governor evidence model (SCG-006).

Authority rules (normative):

* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
* Records are recursively immutable, closed to unknown fields, and restricted
  to strict DAG-JSON types admitted by content identity (no floats).
* Stored CIDs are verified by decode-and-recompute, never trusted alone.
* Private material (secrets, raw private source, witnesses) is rejected.
* Model-written authority claims are rejected; models cannot author trusted
  keys, promotion authority, or self-authorization.
* Unknown enums / statuses fail closed.

The common header binds repository-state, ContextPack, verification-bundle,
generator, provenance, assumptions, and one closed terminal status.  It is a
typed application payload, not a new generic receipt envelope.
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

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

GOVERNOR_ARTIFACT_HEADER_INTERFACE: Final[str] = "GovernorArtifactHeader@1"
GOVERNOR_ARTIFACT_HEADER_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-artifact-header@1"
)
GOVERNOR_PROVENANCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-provenance@1"
)
GOVERNOR_GENERATOR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-generator@1"
)
GOVERNOR_ASSUMPTION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-assumption@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_ASSUMPTIONS: Final[int] = 512
MAX_CID_LIST: Final[int] = 4_096
MAX_TOOL_IDS: Final[int] = 256

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)
_ARTIFACT_KIND_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9_]{0,63}$"
)

# Field-name markers that must never appear in public durable records.
PRIVATE_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "hidden_witness",
        "password",
        "private_key",
        "private_premise",
        "private_source",
        "private_witness",
        "raw_private_source",
        "raw_source",
        "raw_source_text",
        "refresh_token",
        "secret",
        "session_token",
        "source_bytes",
        "source_text",
        "witness",
    }
)

# Keys that assert model-written or self-granted authority — always rejected.
MODEL_AUTHORITY_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "llm_authority",
        "model_authority",
        "model_decision_authority",
        "model_promoted",
        "model_written_authority",
        "provider_authority",
        "self_authorized",
        "self_authorization",
        "trusted_key",
        "trusted_keys",
        "promotion_authority",
    }
)

# Provenance authority sources that models must never claim.
_MODEL_AUTHORITY_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "llm",
        "model",
        "model_output",
        "provider",
        "provider_output",
        "ai",
        "assistant",
    }
)


class SemanticGovernorBaseError(ValueError):
    """Raised when a semantic-governor base record is malformed or unsafe."""


# ---------------------------------------------------------------------------
# Enumerations (closed)
# ---------------------------------------------------------------------------


class ContextSufficiencyState(str, Enum):
    """Closed pre-execution / audit sufficiency vocabulary (exactly nine)."""

    SUFFICIENT = "sufficient"
    SUFFICIENT_WITH_CAVEATS = "sufficient_with_caveats"
    EXPANSION_REQUIRED = "expansion_required"
    FRONTIER_ESCALATION_REQUIRED = "frontier_escalation_required"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    INCONCLUSIVE = "inconclusive"
    INVALID = "invalid"
    STALE = "stale"
    EVALUATION_FAILED = "evaluation_failed"


class GovernorTerminalStatus(str, Enum):
    """Closed terminal status for durable governor artifacts."""

    COMPLETE = "complete"
    REJECTED = "rejected"
    INVALID = "invalid"
    STALE = "stale"
    INCONCLUSIVE = "inconclusive"
    EVALUATION_FAILED = "evaluation_failed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"
    SIMULATED = "simulated"


class ExecutionMode(str, Enum):
    """How the artifact was produced; simulated and live are unambiguous."""

    LIVE = "live"
    SIMULATED = "simulated"
    REPLAY = "replay"


class AuthoritySource(str, Enum):
    """Closed non-model authority sources admitted on provenance."""

    DETERMINISTIC = "deterministic"
    OBSERVED = "observed"
    HUMAN = "human"
    POLICY = "policy"
    RECEIPT = "receipt"
    SCHEMA = "schema"


class AssumptionKind(str, Enum):
    """Closed assumption categories bound on the common header."""

    COVERAGE = "coverage"
    FRESHNESS = "freshness"
    CONFIDENCE = "confidence"
    BUDGET = "budget"
    ROUTE = "route"
    PRIVACY = "privacy"
    VERIFICATION = "verification"
    EXCLUSION = "exclusion"
    ENVIRONMENT = "environment"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise SemanticGovernorBaseError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise SemanticGovernorBaseError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise SemanticGovernorBaseError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise SemanticGovernorBaseError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise SemanticGovernorBaseError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise SemanticGovernorBaseError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name)
    if _VERSION_RE.fullmatch(text) is None:
        raise SemanticGovernorBaseError(
            f"{name} must be a version token matching {_VERSION_RE.pattern}"
        )
    return text


def _artifact_kind(value: Any, name: str = "artifact_kind") -> str:
    text = _text(value, name)
    if _ARTIFACT_KIND_RE.fullmatch(text) is None:
        raise SemanticGovernorBaseError(
            f"{name} must be a lowercase snake-case kind matching "
            f"{_ARTIFACT_KIND_RE.pattern}"
        )
    return text


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise SemanticGovernorBaseError(f"{name} must be a nonnegative integer")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise SemanticGovernorBaseError(f"{name} must be a boolean")
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
        raise SemanticGovernorBaseError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise SemanticGovernorBaseError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise SemanticGovernorBaseError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise SemanticGovernorBaseError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise SemanticGovernorBaseError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_tokens(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise SemanticGovernorBaseError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > MAX_TOOL_IDS:
        raise SemanticGovernorBaseError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise SemanticGovernorBaseError(f"{name} must not contain duplicates")
    return ordered


def _key_is_private(name: str) -> bool:
    lowered = name.lower()
    if lowered in PRIVATE_FIELD_MARKERS:
        return True
    for marker in PRIVATE_FIELD_MARKERS:
        if marker in lowered:
            return True
    return False


def _key_is_model_authority(name: str) -> bool:
    lowered = name.lower()
    if lowered in MODEL_AUTHORITY_FORBIDDEN_KEYS:
        return True
    for marker in MODEL_AUTHORITY_FORBIDDEN_KEYS:
        if marker in lowered:
            return True
    return False


def reject_private_and_model_authority(
    value: Any,
    *,
    path: str = "$",
) -> None:
    """Fail closed when private data or model-written authority is present."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise SemanticGovernorBaseError(
                    f"{path} map keys must be str, got {type(key).__name__}"
                )
            key_path = f"{path}.{key}"
            if _key_is_private(key):
                raise SemanticGovernorBaseError(
                    f"{key_path} rejects private data field {key!r}"
                )
            if _key_is_model_authority(key):
                raise SemanticGovernorBaseError(
                    f"{key_path} rejects model-written authority field {key!r}"
                )
            reject_private_and_model_authority(item, path=key_path)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_private_and_model_authority(item, path=f"{path}[{index}]")
        return


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise SemanticGovernorBaseError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    reject_private_and_model_authority(thawed, path=name)
    return thawed


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticGovernorBaseError(f"{name} must be a mapping")
    result = _require_structured(dict(value), name)
    return _freeze_structured(result) if frozen else result


# ---------------------------------------------------------------------------
# Generator identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GeneratorIdentity:
    """Deterministic producer identity bound into every artifact header."""

    generator_id: str
    generator_version: str
    interface_id: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "generator_id",
            "generator_version",
            "interface_id",
            "generator_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "generator_id", _token(self.generator_id, "generator_id"))
        object.__setattr__(
            self, "generator_version", _version(self.generator_version, "generator_version")
        )
        object.__setattr__(self, "interface_id", _text(self.interface_id, "interface_id"))
        if "@" not in self.interface_id:
            raise SemanticGovernorBaseError(
                "interface_id must be a versioned interface pin (name@N)"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": GOVERNOR_GENERATOR_SCHEMA,
            "generator_id": self.generator_id,
            "generator_version": self.generator_version,
            "interface_id": self.interface_id,
        }

    @property
    def generator_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["generator_cid"] = self.generator_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GeneratorIdentity":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("generator_cid")
        if payload.pop("schema") != GOVERNOR_GENERATOR_SCHEMA:
            raise SemanticGovernorBaseError(
                "unsupported GeneratorIdentity schema version"
            )
        result = cls(
            generator_id=payload["generator_id"],
            generator_version=payload["generator_version"],
            interface_id=payload["interface_id"],
        )
        if claimed != result.generator_cid:
            raise SemanticGovernorBaseError(
                "GeneratorIdentity generator_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArtifactProvenance:
    """Closed provenance for a durable governor artifact.

    ``execution_mode`` makes simulated versus live production unambiguous.
    ``authority_source`` is restricted to non-model sources.
    """

    producer_id: str
    producer_version: str
    execution_mode: ExecutionMode | str
    authority_source: AuthoritySource | str
    input_cids: Sequence[str] = ()
    tool_ids: Sequence[str] = ()
    policy_cid: str | None = None
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "producer_id",
            "producer_version",
            "execution_mode",
            "authority_source",
            "input_cids",
            "tool_ids",
            "policy_cid",
            "notes",
            "provenance_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "producer_id", _token(self.producer_id, "producer_id"))
        object.__setattr__(
            self, "producer_version", _version(self.producer_version, "producer_version")
        )
        mode = _enum(self.execution_mode, ExecutionMode, "execution_mode")
        object.__setattr__(self, "execution_mode", mode)
        authority = str(self.authority_source)
        if authority.lower() in _MODEL_AUTHORITY_SOURCES:
            raise SemanticGovernorBaseError(
                "authority_source rejects model-written authority"
            )
        object.__setattr__(
            self,
            "authority_source",
            _enum(self.authority_source, AuthoritySource, "authority_source"),
        )
        object.__setattr__(
            self, "input_cids", _unique_sorted_cids(list(self.input_cids), "input_cids")
        )
        object.__setattr__(
            self, "tool_ids", _unique_sorted_tokens(list(self.tool_ids), "tool_ids")
        )
        object.__setattr__(self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid"))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": GOVERNOR_PROVENANCE_SCHEMA,
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "execution_mode": self.execution_mode,
            "authority_source": self.authority_source,
            "input_cids": list(self.input_cids),
            "tool_ids": list(self.tool_ids),
            "policy_cid": self.policy_cid,
            "notes": self.notes,
        }

    @property
    def provenance_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["provenance_cid"] = self.provenance_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactProvenance":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("provenance_cid")
        if payload.pop("schema") != GOVERNOR_PROVENANCE_SCHEMA:
            raise SemanticGovernorBaseError(
                "unsupported ArtifactProvenance schema version"
            )
        result = cls(
            producer_id=payload["producer_id"],
            producer_version=payload["producer_version"],
            execution_mode=payload["execution_mode"],
            authority_source=payload["authority_source"],
            input_cids=payload["input_cids"],
            tool_ids=payload["tool_ids"],
            policy_cid=payload["policy_cid"],
            notes=payload["notes"],
        )
        if claimed != result.provenance_cid:
            raise SemanticGovernorBaseError(
                "ArtifactProvenance provenance_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GovernorAssumption:
    """One explicit assumption bound into the common artifact header."""

    assumption_id: str
    kind: AssumptionKind | str
    statement: str
    supporting_cids: Sequence[str] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "assumption_id",
            "kind",
            "statement",
            "supporting_cids",
            "assumption_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "assumption_id", _token(self.assumption_id, "assumption_id")
        )
        object.__setattr__(self, "kind", _enum(self.kind, AssumptionKind, "kind"))
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        object.__setattr__(
            self,
            "supporting_cids",
            _unique_sorted_cids(list(self.supporting_cids), "supporting_cids"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": GOVERNOR_ASSUMPTION_SCHEMA,
            "assumption_id": self.assumption_id,
            "kind": self.kind,
            "statement": self.statement,
            "supporting_cids": list(self.supporting_cids),
        }

    @property
    def assumption_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["assumption_cid"] = self.assumption_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GovernorAssumption":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("assumption_cid")
        if payload.pop("schema") != GOVERNOR_ASSUMPTION_SCHEMA:
            raise SemanticGovernorBaseError(
                "unsupported GovernorAssumption schema version"
            )
        result = cls(
            assumption_id=payload["assumption_id"],
            kind=payload["kind"],
            statement=payload["statement"],
            supporting_cids=payload["supporting_cids"],
        )
        if claimed != result.assumption_cid:
            raise SemanticGovernorBaseError(
                "GovernorAssumption assumption_cid does not verify"
            )
        return result


def _normalize_assumptions(
    values: Sequence[GovernorAssumption | Mapping[str, Any]],
) -> tuple[GovernorAssumption, ...]:
    if not isinstance(values, (list, tuple)):
        raise SemanticGovernorBaseError("assumptions must be a list")
    if len(values) > MAX_ASSUMPTIONS:
        raise SemanticGovernorBaseError("assumptions exceeds maximum length")
    normalized: list[GovernorAssumption] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, GovernorAssumption):
            assumption = item
        elif isinstance(item, Mapping):
            if "assumption_cid" in item:
                assumption = GovernorAssumption.from_dict(item)
            else:
                assumption = GovernorAssumption(
                    assumption_id=item.get("assumption_id", ""),
                    kind=item.get("kind", AssumptionKind.OTHER),
                    statement=item.get("statement", ""),
                    supporting_cids=item.get("supporting_cids", ()),
                )
        else:
            raise SemanticGovernorBaseError(
                "assumptions entries must be GovernorAssumption or mapping"
            )
        if assumption.assumption_id in seen:
            raise SemanticGovernorBaseError(
                f"assumptions must not contain duplicate id "
                f"{assumption.assumption_id!r}"
            )
        seen.add(assumption.assumption_id)
        normalized.append(assumption)
    return tuple(sorted(normalized, key=lambda item: item.assumption_id))


# ---------------------------------------------------------------------------
# Common artifact header
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GovernorArtifactHeader:
    """Common closed header for every durable semantic-governor artifact.

    Interface: ``GovernorArtifactHeader@1``

    Binds repository-state, ContextPack, verification-bundle, generator,
    provenance, assumptions, and one closed terminal status.  Canonical
    identity is ``header_cid`` from ``software_contracts.content``.
    """

    artifact_kind: str
    repository_state_cid: str
    context_pack_cid: str
    verification_bundle_cid: str
    generator: GeneratorIdentity
    provenance: ArtifactProvenance
    terminal_status: GovernorTerminalStatus | str
    assumptions: Sequence[GovernorAssumption] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "artifact_kind",
            "repository_state_cid",
            "context_pack_cid",
            "verification_bundle_cid",
            "generator",
            "provenance",
            "assumptions",
            "terminal_status",
            "metadata",
            "header_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_kind", _artifact_kind(self.artifact_kind, "artifact_kind")
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _cid(self.repository_state_cid, "repository_state_cid"),
        )
        object.__setattr__(
            self, "context_pack_cid", _cid(self.context_pack_cid, "context_pack_cid")
        )
        object.__setattr__(
            self,
            "verification_bundle_cid",
            _cid(self.verification_bundle_cid, "verification_bundle_cid"),
        )
        if not isinstance(self.generator, GeneratorIdentity):
            raise SemanticGovernorBaseError("generator must be GeneratorIdentity")
        if not isinstance(self.provenance, ArtifactProvenance):
            raise SemanticGovernorBaseError("provenance must be ArtifactProvenance")
        object.__setattr__(
            self,
            "terminal_status",
            _enum(self.terminal_status, GovernorTerminalStatus, "terminal_status"),
        )
        object.__setattr__(
            self, "assumptions", _normalize_assumptions(list(self.assumptions))
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        # Simulated production cannot claim a non-simulated terminal status.
        if (
            self.provenance.execution_mode == ExecutionMode.SIMULATED.value
            and self.terminal_status
            not in {
                GovernorTerminalStatus.SIMULATED.value,
                GovernorTerminalStatus.INCONCLUSIVE.value,
                GovernorTerminalStatus.EVALUATION_FAILED.value,
                GovernorTerminalStatus.REJECTED.value,
                GovernorTerminalStatus.INVALID.value,
            }
        ):
            raise SemanticGovernorBaseError(
                "simulated provenance cannot claim non-simulated terminal_status"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": GOVERNOR_ARTIFACT_HEADER_SCHEMA,
            "interface_id": GOVERNOR_ARTIFACT_HEADER_INTERFACE,
            "artifact_kind": self.artifact_kind,
            "repository_state_cid": self.repository_state_cid,
            "context_pack_cid": self.context_pack_cid,
            "verification_bundle_cid": self.verification_bundle_cid,
            "generator": self.generator.identity_payload(),
            "provenance": self.provenance.identity_payload(),
            "assumptions": [item.identity_payload() for item in self.assumptions],
            "terminal_status": self.terminal_status,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def header_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GOVERNOR_ARTIFACT_HEADER_SCHEMA,
            "interface_id": GOVERNOR_ARTIFACT_HEADER_INTERFACE,
            "artifact_kind": self.artifact_kind,
            "repository_state_cid": self.repository_state_cid,
            "context_pack_cid": self.context_pack_cid,
            "verification_bundle_cid": self.verification_bundle_cid,
            "generator": self.generator.to_dict(),
            "provenance": self.provenance.to_dict(),
            "assumptions": [item.to_dict() for item in self.assumptions],
            "terminal_status": self.terminal_status,
            "metadata": _thaw_structured(self.metadata),
            "header_cid": self.header_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GovernorArtifactHeader":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("header_cid")
        schema = payload.pop("schema")
        interface_id = payload.pop("interface_id")
        if schema != GOVERNOR_ARTIFACT_HEADER_SCHEMA:
            raise SemanticGovernorBaseError(
                "unsupported GovernorArtifactHeader schema version"
            )
        if interface_id != GOVERNOR_ARTIFACT_HEADER_INTERFACE:
            raise SemanticGovernorBaseError(
                "unsupported GovernorArtifactHeader interface_id"
            )
        generator_raw = payload["generator"]
        if not isinstance(generator_raw, Mapping):
            raise SemanticGovernorBaseError("generator must be a mapping")
        provenance_raw = payload["provenance"]
        if not isinstance(provenance_raw, Mapping):
            raise SemanticGovernorBaseError("provenance must be a mapping")
        assumptions_raw = payload["assumptions"]
        if not isinstance(assumptions_raw, list):
            raise SemanticGovernorBaseError("assumptions must be a list")
        result = cls(
            artifact_kind=payload["artifact_kind"],
            repository_state_cid=payload["repository_state_cid"],
            context_pack_cid=payload["context_pack_cid"],
            verification_bundle_cid=payload["verification_bundle_cid"],
            generator=GeneratorIdentity.from_dict(generator_raw),
            provenance=ArtifactProvenance.from_dict(provenance_raw),
            terminal_status=payload["terminal_status"],
            assumptions=assumptions_raw,
            metadata=payload["metadata"],
        )
        if claimed != result.header_cid:
            raise SemanticGovernorBaseError(
                "GovernorArtifactHeader header_cid does not verify"
            )
        return result


def verify_header_identity(header: GovernorArtifactHeader | Mapping[str, Any]) -> str:
    """Recompute and return the header CID; raise on forged or malformed input."""

    if isinstance(header, GovernorArtifactHeader):
        sealed = header
    elif isinstance(header, Mapping):
        sealed = GovernorArtifactHeader.from_dict(header)
    else:
        raise SemanticGovernorBaseError(
            "header must be GovernorArtifactHeader or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.header_cid:
        raise SemanticGovernorBaseError(
            "header_cid does not match recomputed identity"
        )
    return recomputed


def context_sufficiency_states() -> tuple[str, ...]:
    """Return the closed sufficiency vocabulary in declaration order."""

    return tuple(item.value for item in ContextSufficiencyState)


def governor_terminal_statuses() -> tuple[str, ...]:
    """Return the closed terminal-status vocabulary in declaration order."""

    return tuple(item.value for item in GovernorTerminalStatus)


__all__ = [
    "AssumptionKind",
    "ArtifactProvenance",
    "AuthoritySource",
    "ContextSufficiencyState",
    "ExecutionMode",
    "GOVERNOR_ARTIFACT_HEADER_INTERFACE",
    "GOVERNOR_ARTIFACT_HEADER_SCHEMA",
    "GOVERNOR_ASSUMPTION_SCHEMA",
    "GOVERNOR_GENERATOR_SCHEMA",
    "GOVERNOR_PROVENANCE_SCHEMA",
    "GeneratorIdentity",
    "GovernorArtifactHeader",
    "GovernorAssumption",
    "GovernorTerminalStatus",
    "MAX_ASSUMPTIONS",
    "MAX_CID_LIST",
    "MAX_TEXT_CHARS",
    "MAX_TOOL_IDS",
    "MODEL_AUTHORITY_FORBIDDEN_KEYS",
    "PRIVATE_FIELD_MARKERS",
    "SemanticGovernorBaseError",
    "context_sufficiency_states",
    "governor_terminal_statuses",
    "reject_private_and_model_authority",
    "verify_header_identity",
]
