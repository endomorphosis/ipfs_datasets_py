"""Common adversarial-assurance artifact headers, identities, and vocabularies.

This module exclusively owns ``AssuranceArtifactHeader@1`` and the closed
status / provenance vocabularies shared by every durable AAE evidence model
(AAE-007).

Authority rules (normative):

* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
* Records are recursively immutable, closed to unknown fields, and restricted
  to strict DAG-JSON types admitted by content identity (no floats, no host
  objects, no repr fallbacks).
* Stored CIDs are verified by decode-and-recompute, never trusted alone.
* Every persisted artifact binds repository, repository-state, target,
  capsule, proof-unit, environment, dependency-lock, version, status,
  provenance, and canonical identity fields.
* Private material and model-written authority claims are rejected.
* Unknown enums / statuses fail closed.
* Simulated provenance cannot claim a live-complete terminal status.
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

ASSURANCE_ARTIFACT_HEADER_INTERFACE: Final[str] = "AssuranceArtifactHeader@1"
ASSURANCE_ARTIFACT_HEADER_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-artifact-header@1"
)
ASSURANCE_PROVENANCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-provenance@1"
)
ASSURANCE_GENERATOR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-generator@1"
)
ASSURANCE_VERSION_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-version-binding@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_ID_LIST: Final[int] = 4_096
MAX_TOOL_IDS: Final[int] = 256

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)
_ARTIFACT_KIND_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9_]{0,63}$"
)
_REPOSITORY_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,255}$"
)
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
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

# Host / environment fallback markers rejected on durable records.
HOST_FALLBACK_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "cwd",
        "env",
        "getenv",
        "hostname",
        "host_cwd",
        "host_env",
        "host_fallback",
        "host_path",
        "local_path",
        "os_environ",
        "platform_fallback",
        "pwd",
        "socket_hostname",
        "tmpdir",
        "user_home",
        "workdir",
        "working_directory",
    }
)


class AssuranceBaseError(ValueError):
    """Raised when an adversarial-assurance common record is malformed or unsafe."""


# ---------------------------------------------------------------------------
# Enumerations (closed)
# ---------------------------------------------------------------------------


class AssuranceTerminalStatus(str, Enum):
    """Closed terminal status for durable adversarial-assurance artifacts."""

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


# Terminal statuses allowed when provenance execution_mode is simulated.
_SIMULATED_ALLOWED_TERMINAL: Final[frozenset[str]] = frozenset(
    {
        AssuranceTerminalStatus.SIMULATED.value,
        AssuranceTerminalStatus.INCONCLUSIVE.value,
        AssuranceTerminalStatus.EVALUATION_FAILED.value,
        AssuranceTerminalStatus.REJECTED.value,
        AssuranceTerminalStatus.INVALID.value,
        AssuranceTerminalStatus.CANCELLED.value,
        AssuranceTerminalStatus.UNAVAILABLE.value,
    }
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise AssuranceBaseError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise AssuranceBaseError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise AssuranceBaseError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise AssuranceBaseError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise AssuranceBaseError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise AssuranceBaseError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name)
    if _VERSION_RE.fullmatch(text) is None:
        raise AssuranceBaseError(
            f"{name} must be a version token matching {_VERSION_RE.pattern}"
        )
    return text


def _artifact_kind(value: Any, name: str = "artifact_kind") -> str:
    text = _text(value, name)
    if _ARTIFACT_KIND_RE.fullmatch(text) is None:
        raise AssuranceBaseError(
            f"{name} must be a lowercase snake-case kind matching "
            f"{_ARTIFACT_KIND_RE.pattern}"
        )
    return text


def _repository_id(value: Any, name: str = "repository_id") -> str:
    text = _text(value, name)
    if _REPOSITORY_ID_RE.fullmatch(text) is None:
        raise AssuranceBaseError(
            f"{name} must be a repository identity matching "
            f"{_REPOSITORY_ID_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise AssuranceBaseError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


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
        raise AssuranceBaseError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise AssuranceBaseError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AssuranceBaseError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise AssuranceBaseError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise AssuranceBaseError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_tokens(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AssuranceBaseError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > MAX_TOOL_IDS:
        raise AssuranceBaseError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise AssuranceBaseError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_symbol_ids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AssuranceBaseError(f"{name} must be a list")
    ordered = tuple(sorted(_symbol_id(value, name) for value in values))
    if len(ordered) > MAX_ID_LIST:
        raise AssuranceBaseError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise AssuranceBaseError(f"{name} must not contain duplicates")
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


def _key_is_host_fallback(name: str) -> bool:
    lowered = name.lower()
    if lowered in HOST_FALLBACK_MARKERS:
        return True
    for marker in HOST_FALLBACK_MARKERS:
        if marker in lowered:
            return True
    return False


def reject_private_model_authority_and_host_fallbacks(
    value: Any,
    *,
    path: str = "$",
) -> None:
    """Fail closed when private data, model authority, or host fallbacks appear."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise AssuranceBaseError(
                    f"{path} map keys must be str, got {type(key).__name__}"
                )
            key_path = f"{path}.{key}"
            if _key_is_private(key):
                raise AssuranceBaseError(
                    f"{key_path} rejects private data field {key!r}"
                )
            if _key_is_model_authority(key):
                raise AssuranceBaseError(
                    f"{key_path} rejects model-written authority field {key!r}"
                )
            if _key_is_host_fallback(key):
                raise AssuranceBaseError(
                    f"{key_path} rejects host fallback field {key!r}"
                )
            reject_private_model_authority_and_host_fallbacks(item, path=key_path)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_private_model_authority_and_host_fallbacks(
                item, path=f"{path}[{index}]"
            )
        return


# Back-compat alias for callers that mirror the governor naming.
reject_private_and_model_authority = reject_private_model_authority_and_host_fallbacks


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise AssuranceBaseError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    reject_private_model_authority_and_host_fallbacks(thawed, path=name)
    return thawed


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AssuranceBaseError(f"{name} must be a mapping")
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
            raise AssuranceBaseError(
                "interface_id must be a versioned interface pin (name@N)"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_GENERATOR_SCHEMA,
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
        if payload.pop("schema") != ASSURANCE_GENERATOR_SCHEMA:
            raise AssuranceBaseError(
                "unsupported GeneratorIdentity schema version"
            )
        result = cls(
            generator_id=payload["generator_id"],
            generator_version=payload["generator_version"],
            interface_id=payload["interface_id"],
        )
        if claimed != result.generator_cid:
            raise AssuranceBaseError(
                "GeneratorIdentity generator_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Version binding (operator / campaign policy / generator)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VersionBinding:
    """Operator, campaign-policy, and generator version pins for one artifact."""

    operator_id: str
    operator_version: str
    campaign_policy_id: str
    campaign_policy_version: str
    generator: GeneratorIdentity

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "operator_id",
            "operator_version",
            "campaign_policy_id",
            "campaign_policy_version",
            "generator",
            "version_binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator_id", _token(self.operator_id, "operator_id"))
        object.__setattr__(
            self, "operator_version", _version(self.operator_version, "operator_version")
        )
        object.__setattr__(
            self,
            "campaign_policy_id",
            _token(self.campaign_policy_id, "campaign_policy_id"),
        )
        object.__setattr__(
            self,
            "campaign_policy_version",
            _version(self.campaign_policy_version, "campaign_policy_version"),
        )
        if not isinstance(self.generator, GeneratorIdentity):
            raise AssuranceBaseError("generator must be GeneratorIdentity")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_VERSION_BINDING_SCHEMA,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "campaign_policy_id": self.campaign_policy_id,
            "campaign_policy_version": self.campaign_policy_version,
            "generator": self.generator.identity_payload(),
        }

    @property
    def version_binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_VERSION_BINDING_SCHEMA,
            "operator_id": self.operator_id,
            "operator_version": self.operator_version,
            "campaign_policy_id": self.campaign_policy_id,
            "campaign_policy_version": self.campaign_policy_version,
            "generator": self.generator.to_dict(),
            "version_binding_cid": self.version_binding_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VersionBinding":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("version_binding_cid")
        if payload.pop("schema") != ASSURANCE_VERSION_BINDING_SCHEMA:
            raise AssuranceBaseError(
                "unsupported VersionBinding schema version"
            )
        generator_raw = payload["generator"]
        if not isinstance(generator_raw, Mapping):
            raise AssuranceBaseError("generator must be a mapping")
        result = cls(
            operator_id=payload["operator_id"],
            operator_version=payload["operator_version"],
            campaign_policy_id=payload["campaign_policy_id"],
            campaign_policy_version=payload["campaign_policy_version"],
            generator=GeneratorIdentity.from_dict(generator_raw),
        )
        if claimed != result.version_binding_cid:
            raise AssuranceBaseError(
                "VersionBinding version_binding_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArtifactProvenance:
    """Closed provenance for a durable adversarial-assurance artifact.

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
            raise AssuranceBaseError(
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
            "schema": ASSURANCE_PROVENANCE_SCHEMA,
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
        if payload.pop("schema") != ASSURANCE_PROVENANCE_SCHEMA:
            raise AssuranceBaseError(
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
            raise AssuranceBaseError(
                "ArtifactProvenance provenance_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Common artifact header
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssuranceArtifactHeader:
    """Common closed header for every durable adversarial-assurance artifact.

    Interface: ``AssuranceArtifactHeader@1``

    Binds repository identity, repository-state root, target symbol/artifact
    identities, semantic-capsule and proof-unit identities, environment and
    dependency-lock identities, operator/campaign-policy/generator versions,
    terminal status, provenance, referenced receipt/proof identities, and
    canonical ``header_cid`` identity from ``software_contracts.content``.
    """

    artifact_kind: str
    repository_id: str
    repository_state_cid: str
    target_symbol_ids: Sequence[str]
    target_artifact_cids: Sequence[str]
    capsule_cids: Sequence[str]
    proof_unit_cids: Sequence[str]
    environment_cid: str
    dependency_lock_cid: str
    versions: VersionBinding
    provenance: ArtifactProvenance
    terminal_status: AssuranceTerminalStatus | str
    receipt_cids: Sequence[str] = ()
    proof_cids: Sequence[str] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "artifact_kind",
            "repository_id",
            "repository_state_cid",
            "target_symbol_ids",
            "target_artifact_cids",
            "capsule_cids",
            "proof_unit_cids",
            "environment_cid",
            "dependency_lock_cid",
            "versions",
            "provenance",
            "terminal_status",
            "receipt_cids",
            "proof_cids",
            "metadata",
            "header_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_kind", _artifact_kind(self.artifact_kind, "artifact_kind")
        )
        object.__setattr__(
            self, "repository_id", _repository_id(self.repository_id, "repository_id")
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _cid(self.repository_state_cid, "repository_state_cid"),
        )
        object.__setattr__(
            self,
            "target_symbol_ids",
            _unique_sorted_symbol_ids(
                list(self.target_symbol_ids), "target_symbol_ids"
            ),
        )
        object.__setattr__(
            self,
            "target_artifact_cids",
            _unique_sorted_cids(
                list(self.target_artifact_cids), "target_artifact_cids"
            ),
        )
        object.__setattr__(
            self,
            "capsule_cids",
            _unique_sorted_cids(list(self.capsule_cids), "capsule_cids"),
        )
        object.__setattr__(
            self,
            "proof_unit_cids",
            _unique_sorted_cids(list(self.proof_unit_cids), "proof_unit_cids"),
        )
        object.__setattr__(
            self, "environment_cid", _cid(self.environment_cid, "environment_cid")
        )
        object.__setattr__(
            self,
            "dependency_lock_cid",
            _cid(self.dependency_lock_cid, "dependency_lock_cid"),
        )
        if not isinstance(self.versions, VersionBinding):
            raise AssuranceBaseError("versions must be VersionBinding")
        if not isinstance(self.provenance, ArtifactProvenance):
            raise AssuranceBaseError("provenance must be ArtifactProvenance")
        object.__setattr__(
            self,
            "terminal_status",
            _enum(self.terminal_status, AssuranceTerminalStatus, "terminal_status"),
        )
        object.__setattr__(
            self,
            "receipt_cids",
            _unique_sorted_cids(list(self.receipt_cids), "receipt_cids"),
        )
        object.__setattr__(
            self, "proof_cids", _unique_sorted_cids(list(self.proof_cids), "proof_cids")
        )
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        # Simulated production cannot claim a non-simulated terminal status.
        if (
            self.provenance.execution_mode == ExecutionMode.SIMULATED.value
            and self.terminal_status not in _SIMULATED_ALLOWED_TERMINAL
        ):
            raise AssuranceBaseError(
                "simulated provenance cannot claim non-simulated terminal_status"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_ARTIFACT_HEADER_SCHEMA,
            "interface_id": ASSURANCE_ARTIFACT_HEADER_INTERFACE,
            "artifact_kind": self.artifact_kind,
            "repository_id": self.repository_id,
            "repository_state_cid": self.repository_state_cid,
            "target_symbol_ids": list(self.target_symbol_ids),
            "target_artifact_cids": list(self.target_artifact_cids),
            "capsule_cids": list(self.capsule_cids),
            "proof_unit_cids": list(self.proof_unit_cids),
            "environment_cid": self.environment_cid,
            "dependency_lock_cid": self.dependency_lock_cid,
            "versions": self.versions.identity_payload(),
            "provenance": self.provenance.identity_payload(),
            "terminal_status": self.terminal_status,
            "receipt_cids": list(self.receipt_cids),
            "proof_cids": list(self.proof_cids),
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def header_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_ARTIFACT_HEADER_SCHEMA,
            "interface_id": ASSURANCE_ARTIFACT_HEADER_INTERFACE,
            "artifact_kind": self.artifact_kind,
            "repository_id": self.repository_id,
            "repository_state_cid": self.repository_state_cid,
            "target_symbol_ids": list(self.target_symbol_ids),
            "target_artifact_cids": list(self.target_artifact_cids),
            "capsule_cids": list(self.capsule_cids),
            "proof_unit_cids": list(self.proof_unit_cids),
            "environment_cid": self.environment_cid,
            "dependency_lock_cid": self.dependency_lock_cid,
            "versions": self.versions.to_dict(),
            "provenance": self.provenance.to_dict(),
            "terminal_status": self.terminal_status,
            "receipt_cids": list(self.receipt_cids),
            "proof_cids": list(self.proof_cids),
            "metadata": _thaw_structured(self.metadata),
            "header_cid": self.header_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AssuranceArtifactHeader":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("header_cid")
        schema = payload.pop("schema")
        interface_id = payload.pop("interface_id")
        if schema != ASSURANCE_ARTIFACT_HEADER_SCHEMA:
            raise AssuranceBaseError(
                "unsupported AssuranceArtifactHeader schema version"
            )
        if interface_id != ASSURANCE_ARTIFACT_HEADER_INTERFACE:
            raise AssuranceBaseError(
                "unsupported AssuranceArtifactHeader interface_id"
            )
        versions_raw = payload["versions"]
        if not isinstance(versions_raw, Mapping):
            raise AssuranceBaseError("versions must be a mapping")
        provenance_raw = payload["provenance"]
        if not isinstance(provenance_raw, Mapping):
            raise AssuranceBaseError("provenance must be a mapping")
        result = cls(
            artifact_kind=payload["artifact_kind"],
            repository_id=payload["repository_id"],
            repository_state_cid=payload["repository_state_cid"],
            target_symbol_ids=payload["target_symbol_ids"],
            target_artifact_cids=payload["target_artifact_cids"],
            capsule_cids=payload["capsule_cids"],
            proof_unit_cids=payload["proof_unit_cids"],
            environment_cid=payload["environment_cid"],
            dependency_lock_cid=payload["dependency_lock_cid"],
            versions=VersionBinding.from_dict(versions_raw),
            provenance=ArtifactProvenance.from_dict(provenance_raw),
            terminal_status=payload["terminal_status"],
            receipt_cids=payload["receipt_cids"],
            proof_cids=payload["proof_cids"],
            metadata=payload["metadata"],
        )
        if claimed != result.header_cid:
            raise AssuranceBaseError(
                "AssuranceArtifactHeader header_cid identity mismatch"
            )
        return result


def verify_header_identity(
    header: AssuranceArtifactHeader | Mapping[str, Any],
) -> str:
    """Recompute and return the header CID; raise on forged or malformed input."""

    if isinstance(header, AssuranceArtifactHeader):
        sealed = header
    elif isinstance(header, Mapping):
        sealed = AssuranceArtifactHeader.from_dict(header)
    else:
        raise AssuranceBaseError(
            "header must be AssuranceArtifactHeader or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.header_cid:
        raise AssuranceBaseError(
            "header_cid identity mismatch with recomputed identity"
        )
    return recomputed


def assurance_terminal_statuses() -> tuple[str, ...]:
    """Return the closed terminal-status vocabulary in declaration order."""

    return tuple(item.value for item in AssuranceTerminalStatus)


def execution_modes() -> tuple[str, ...]:
    """Return the closed execution-mode vocabulary in declaration order."""

    return tuple(item.value for item in ExecutionMode)


def authority_sources() -> tuple[str, ...]:
    """Return the closed authority-source vocabulary in declaration order."""

    return tuple(item.value for item in AuthoritySource)


__all__ = [
    "ASSURANCE_ARTIFACT_HEADER_INTERFACE",
    "ASSURANCE_ARTIFACT_HEADER_SCHEMA",
    "ASSURANCE_GENERATOR_SCHEMA",
    "ASSURANCE_PROVENANCE_SCHEMA",
    "ASSURANCE_VERSION_BINDING_SCHEMA",
    "ArtifactProvenance",
    "AssuranceArtifactHeader",
    "AssuranceBaseError",
    "AssuranceTerminalStatus",
    "AuthoritySource",
    "ExecutionMode",
    "GeneratorIdentity",
    "HOST_FALLBACK_MARKERS",
    "MAX_CID_LIST",
    "MAX_ID_LIST",
    "MAX_TEXT_CHARS",
    "MAX_TOOL_IDS",
    "MODEL_AUTHORITY_FORBIDDEN_KEYS",
    "PRIVATE_FIELD_MARKERS",
    "VersionBinding",
    "assurance_terminal_statuses",
    "authority_sources",
    "execution_modes",
    "reject_private_and_model_authority",
    "reject_private_model_authority_and_host_fallbacks",
    "verify_header_identity",
]
