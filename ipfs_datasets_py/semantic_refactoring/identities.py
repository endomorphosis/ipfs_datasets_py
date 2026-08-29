"""Closed SPAR identity contracts (@1).

This module extends current ``ipfs_datasets_py`` semantic authority with
``SemanticArtifactIdentitySet@1`` and golden move vectors.  It does not replace
existing @1 capsule, semantic-index, or content-CID readers, does not mint a
second content-identity profile, and does not import or export providers,
models, or completion authority.

Normative rules:

* A CID identifies exact canonical bytes under the declared codec/profile, not
  universal meaning.
* A move may preserve implementation/contract identity while changing binding
  and compatibility identity; that delta is explicit.
* Timestamps, process IDs, local paths, and model output are excluded from
  semantic identity.
* Accepted ``@1`` payloads are never rewritten in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Mapping, Sequence
import json
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    PROFILE_ID,
    STRUCTURED_CODEC,
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)


TASK_ID: Final[str] = "SPAR-003"
GOAL_ID: Final[str] = "SPAR-G012"
PROGRAM: Final[str] = "semantic-preserving-autonomous-remodularization-v1"
AUTHORITY: Final[str] = "formal semantic authority"
AUTHORITY_OWNER: Final[str] = "ipfs_datasets_py"

SEMANTIC_ARTIFACT_IDENTITY_SET_INTERFACE: Final[str] = "SemanticArtifactIdentitySet@1"
IDENTITY_MOVE_VECTOR_INTERFACE: Final[str] = "IdentityMoveVector@1"
IDENTITY_DELTA_INTERFACE: Final[str] = "IdentityDelta@1"

SEMANTIC_ARTIFACT_IDENTITY_SET_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.semantic-artifact-identity-set@1"
)
IDENTITY_MOVE_VECTOR_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.identity-move-vector@1"
)
IDENTITY_DELTA_SCHEMA: Final[str] = (
    "ipfs-datasets.semantic-refactoring.identity-delta@1"
)

IDENTITY_CONTRACT_VERSION: Final[str] = "1"
IDENTITY_CID_CODEC: Final[str] = STRUCTURED_CODEC
IDENTITY_CID_PROFILE: Final[str] = PROFILE_ID

IDENTITIES_CAN_AUTHORIZE_TRANSITION: Final[bool] = False
IDENTITIES_CAN_AUTHORIZE_COMPLETION: Final[bool] = False
IDENTITIES_CAN_CREATE_AUTHORITY: Final[bool] = False
VECTOR_SIMILARITY_IS_AUTHORITY: Final[bool] = False
MODEL_OUTPUT_IS_PROPOSAL_ONLY: Final[bool] = True
TEST_PASS_IS_NOT_COMPLETION: Final[bool] = True
MARKDOWN_IS_NOT_COMPLETION: Final[bool] = True
WORKER_SELF_APPROVAL: Final[bool] = False
DUCKLAKE_IS_AUTHORITY: Final[bool] = False

# Inventory order is normative.  ``function_capsule_cid`` is the subject
# aggregate capsule identity, not this record's own identity_set_cid.
IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "stable_symbol_id",
    "source_cid",
    "cst_cid",
    "ast_cid",
    "implementation_ir_cid",
    "symbol_binding_cid",
    "interface_contract_cid",
    "effect_summary_cid",
    "state_footprint_cid",
    "dependency_slice_cid",
    "behavior_summary_cid",
    "initialization_dependency_cid",
    "public_compatibility_cid",
    "validation_profile_cid",
    "provenance_cid",
    "semantic_state_root_cid",
    "function_capsule_cid",
)
IDENTITY_FIELD_SET: Final[frozenset[str]] = frozenset(IDENTITY_FIELDS)

# Capsule @1 identity_payload fields; the aggregate is derived there.
EXISTING_AT1_IDENTITY_DIMENSIONS: Final[tuple[str, ...]] = tuple(
    name for name in IDENTITY_FIELDS if name != "function_capsule_cid"
)

FORBIDDEN_OBSERVATIONAL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "timestamp",
        "timestamps",
        "clock",
        "clocks",
        "wall_clock",
        "process_id",
        "pid",
        "local_path",
        "local_paths",
        "checkout_path",
        "store_path",
        "model_output",
        "provider_output",
        "llm_output",
        "prompt",
        "prompts",
        "model",
        "provider",
        "lease",
        "fence",
        "generation",
        "receipt",
        "acceptance",
    }
)

MAX_TEXT_CHARS: Final[int] = 16_384


class IdentityContractError(ValueError):
    """Raised when a SPAR identity contract record is malformed."""


class IdentityFamily(str, Enum):
    STABLE_SYMBOL = "stable_symbol"
    SOURCE = "source"
    IMPLEMENTATION = "implementation"
    BINDING = "binding"
    CONTRACT = "contract"
    EFFECT = "effect"
    STATE = "state"
    DEPENDENCY = "dependency"
    BEHAVIOR = "behavior"
    INITIALIZATION = "initialization"
    COMPATIBILITY = "compatibility"
    VALIDATION = "validation"
    PROVENANCE = "provenance"
    SEMANTIC_STATE = "semantic_state"
    AGGREGATE = "aggregate"


class IdentitySensitivity(str, Enum):
    LOCATION_INDEPENDENT = "location_independent"
    LOCATION_SENSITIVE = "location_sensitive"
    AGGREGATE = "aggregate"


class IdentityMoveKind(str, Enum):
    SEMANTIC_PRESERVING_RELOCATION = "semantic_preserving_relocation"
    IMPLEMENTATION_EDIT = "implementation_edit"
    CONTRACT_EDIT = "contract_edit"
    EFFECT_EDIT = "effect_edit"
    STATE_EDIT = "state_edit"
    DEPENDENCY_EDIT = "dependency_edit"
    BEHAVIOR_EDIT = "behavior_edit"
    VALIDATION_EDIT = "validation_edit"


PRIMARY_IDENTITY_FAMILIES: Final[tuple[str, ...]] = (
    IdentityFamily.IMPLEMENTATION.value,
    IdentityFamily.BINDING.value,
    IdentityFamily.CONTRACT.value,
    IdentityFamily.EFFECT.value,
    IdentityFamily.STATE.value,
    IdentityFamily.DEPENDENCY.value,
    IdentityFamily.BEHAVIOR.value,
    IdentityFamily.VALIDATION.value,
)

_FIELD_FAMILY: Final[Mapping[str, str]] = MappingProxyType(
    {
        "stable_symbol_id": IdentityFamily.STABLE_SYMBOL.value,
        "source_cid": IdentityFamily.SOURCE.value,
        "cst_cid": IdentityFamily.SOURCE.value,
        "ast_cid": IdentityFamily.SOURCE.value,
        "implementation_ir_cid": IdentityFamily.IMPLEMENTATION.value,
        "symbol_binding_cid": IdentityFamily.BINDING.value,
        "interface_contract_cid": IdentityFamily.CONTRACT.value,
        "effect_summary_cid": IdentityFamily.EFFECT.value,
        "state_footprint_cid": IdentityFamily.STATE.value,
        "dependency_slice_cid": IdentityFamily.DEPENDENCY.value,
        "behavior_summary_cid": IdentityFamily.BEHAVIOR.value,
        "initialization_dependency_cid": IdentityFamily.INITIALIZATION.value,
        "public_compatibility_cid": IdentityFamily.COMPATIBILITY.value,
        "validation_profile_cid": IdentityFamily.VALIDATION.value,
        "provenance_cid": IdentityFamily.PROVENANCE.value,
        "semantic_state_root_cid": IdentityFamily.SEMANTIC_STATE.value,
        "function_capsule_cid": IdentityFamily.AGGREGATE.value,
    }
)

_FIELD_SENSITIVITY: Final[Mapping[str, str]] = MappingProxyType(
    {
        "stable_symbol_id": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "source_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "cst_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "ast_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "implementation_ir_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "symbol_binding_cid": IdentitySensitivity.LOCATION_SENSITIVE.value,
        "interface_contract_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "effect_summary_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "state_footprint_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "dependency_slice_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "behavior_summary_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "initialization_dependency_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "public_compatibility_cid": IdentitySensitivity.LOCATION_SENSITIVE.value,
        "validation_profile_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "provenance_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "semantic_state_root_cid": IdentitySensitivity.LOCATION_INDEPENDENT.value,
        "function_capsule_cid": IdentitySensitivity.AGGREGATE.value,
    }
)

LOCATION_INDEPENDENT_IDENTITY_FIELDS: Final[tuple[str, ...]] = tuple(
    name
    for name in IDENTITY_FIELDS
    if _FIELD_SENSITIVITY[name] == IdentitySensitivity.LOCATION_INDEPENDENT.value
)
LOCATION_SENSITIVE_IDENTITY_FIELDS: Final[tuple[str, ...]] = tuple(
    name
    for name in IDENTITY_FIELDS
    if _FIELD_SENSITIVITY[name] == IdentitySensitivity.LOCATION_SENSITIVE.value
)
AGGREGATE_IDENTITY_FIELDS: Final[tuple[str, ...]] = tuple(
    name
    for name in IDENTITY_FIELDS
    if _FIELD_SENSITIVITY[name] == IdentitySensitivity.AGGREGATE.value
)

IMPLEMENTATION_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("implementation_ir_cid",)
BINDING_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("symbol_binding_cid",)
CONTRACT_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("interface_contract_cid",)
EFFECT_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("effect_summary_cid",)
STATE_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("state_footprint_cid",)
DEPENDENCY_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("dependency_slice_cid",)
BEHAVIOR_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("behavior_summary_cid",)
VALIDATION_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("validation_profile_cid",)
COMPATIBILITY_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("public_compatibility_cid",)
# Plan rule: a move may preserve implementation/contract identity while
# changing binding/compatibility identity.  These tuples are that split.
IMPLEMENTATION_AND_CONTRACT_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    *IMPLEMENTATION_IDENTITY_FIELDS,
    *CONTRACT_IDENTITY_FIELDS,
)
BINDING_AND_COMPATIBILITY_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    *BINDING_IDENTITY_FIELDS,
    *COMPATIBILITY_IDENTITY_FIELDS,
)

_KIND_REQUIRED_CHANGED_FAMILIES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        IdentityMoveKind.SEMANTIC_PRESERVING_RELOCATION.value: frozenset(
            {
                IdentityFamily.BINDING.value,
                IdentityFamily.COMPATIBILITY.value,
                IdentityFamily.AGGREGATE.value,
            }
        ),
        IdentityMoveKind.IMPLEMENTATION_EDIT.value: frozenset(
            {IdentityFamily.IMPLEMENTATION.value, IdentityFamily.AGGREGATE.value}
        ),
        IdentityMoveKind.CONTRACT_EDIT.value: frozenset(
            {IdentityFamily.CONTRACT.value, IdentityFamily.AGGREGATE.value}
        ),
        IdentityMoveKind.EFFECT_EDIT.value: frozenset(
            {IdentityFamily.EFFECT.value, IdentityFamily.AGGREGATE.value}
        ),
        IdentityMoveKind.STATE_EDIT.value: frozenset(
            {IdentityFamily.STATE.value, IdentityFamily.AGGREGATE.value}
        ),
        IdentityMoveKind.DEPENDENCY_EDIT.value: frozenset(
            {IdentityFamily.DEPENDENCY.value, IdentityFamily.AGGREGATE.value}
        ),
        IdentityMoveKind.BEHAVIOR_EDIT.value: frozenset(
            {IdentityFamily.BEHAVIOR.value, IdentityFamily.AGGREGATE.value}
        ),
        IdentityMoveKind.VALIDATION_EDIT.value: frozenset(
            {IdentityFamily.VALIDATION.value, IdentityFamily.AGGREGATE.value}
        ),
    }
)

_KIND_EDIT_FAMILY: Final[Mapping[str, str]] = MappingProxyType(
    {
        IdentityMoveKind.IMPLEMENTATION_EDIT.value: IdentityFamily.IMPLEMENTATION.value,
        IdentityMoveKind.CONTRACT_EDIT.value: IdentityFamily.CONTRACT.value,
        IdentityMoveKind.EFFECT_EDIT.value: IdentityFamily.EFFECT.value,
        IdentityMoveKind.STATE_EDIT.value: IdentityFamily.STATE.value,
        IdentityMoveKind.DEPENDENCY_EDIT.value: IdentityFamily.DEPENDENCY.value,
        IdentityMoveKind.BEHAVIOR_EDIT.value: IdentityFamily.BEHAVIOR.value,
        IdentityMoveKind.VALIDATION_EDIT.value: IdentityFamily.VALIDATION.value,
    }
)


@dataclass(frozen=True, slots=True)
class IdentityFieldSpec:
    """Closed catalog entry for one declared identity dimension."""

    name: str
    family: str
    sensitivity: str


IDENTITY_FIELD_SPECS: Final[tuple[IdentityFieldSpec, ...]] = tuple(
    IdentityFieldSpec(
        name=name,
        family=_FIELD_FAMILY[name],
        sensitivity=_FIELD_SENSITIVITY[name],
    )
    for name in IDENTITY_FIELDS
)


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise IdentityContractError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise IdentityContractError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise IdentityContractError(f"{name} contains invalid text")
    return value


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise IdentityContractError(f"{name} must be a valid CID") from exc


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise IdentityContractError(f"{name} has unsupported value {value!r}") from exc


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping) or isinstance(data, (str, bytes, bytearray)):
        raise IdentityContractError(f"{name} must be a mapping")
    overlap = FORBIDDEN_OBSERVATIONAL_FIELDS.intersection(data)
    if overlap:
        raise IdentityContractError(
            f"{name} excludes observational fields {sorted(overlap)}"
        )
    actual = set(data)
    if actual != fields:
        raise IdentityContractError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _require_dag_json(value: Any, name: str) -> Any:
    try:
        validate_structured_value(value)
    except Exception as exc:
        raise IdentityContractError(f"{name} must be strict DAG-JSON") from exc
    return value


def _unique_sorted_fields(values: Any, name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise IdentityContractError(f"{name} must be a list")
    ordered = tuple(sorted(_text(item, name) for item in values))
    if len(ordered) != len(set(ordered)):
        raise IdentityContractError(f"{name} must not contain duplicates")
    unknown = [item for item in ordered if item not in IDENTITY_FIELD_SET]
    if unknown:
        raise IdentityContractError(
            f"{name} contains unknown identity fields {unknown}"
        )
    return ordered


def identity_cid_profile() -> dict[str, str]:
    """Declare the reused datasets structured CID profile (not a second codec)."""

    return {
        "profile_id": IDENTITY_CID_PROFILE,
        "codec": IDENTITY_CID_CODEC,
        "contract_version": IDENTITY_CONTRACT_VERSION,
        "rule": (
            "CID identifies exact canonical bytes under declared codec/profile, "
            "not universal meaning"
        ),
    }


def is_forbidden_observational_field(name: str) -> bool:
    """True when ``name`` is excluded from semantic identity."""

    if type(name) is not str or not name:
        return False
    return name in FORBIDDEN_OBSERVATIONAL_FIELDS


def classify_identity_field(name: str) -> IdentityFieldSpec:
    """Return the closed family/sensitivity catalog entry for one field."""

    field_name = _text(name, "identity field")
    if field_name in FORBIDDEN_OBSERVATIONAL_FIELDS:
        raise IdentityContractError(
            f"observational field {field_name!r} is excluded from semantic identity"
        )
    if field_name not in IDENTITY_FIELD_SET:
        raise IdentityContractError(f"unknown identity field {field_name!r}")
    return IdentityFieldSpec(
        name=field_name,
        family=_FIELD_FAMILY[field_name],
        sensitivity=_FIELD_SENSITIVITY[field_name],
    )


def fields_for_family(family: IdentityFamily | str) -> tuple[str, ...]:
    family_name = _enum(family, IdentityFamily, "family")
    return tuple(name for name in IDENTITY_FIELDS if _FIELD_FAMILY[name] == family_name)


def fields_for_sensitivity(sensitivity: IdentitySensitivity | str) -> tuple[str, ...]:
    sensitivity_name = _enum(sensitivity, IdentitySensitivity, "sensitivity")
    return tuple(
        name for name in IDENTITY_FIELDS if _FIELD_SENSITIVITY[name] == sensitivity_name
    )


def _reject_observational(payload: Mapping[str, Any], name: str) -> None:
    overlap = FORBIDDEN_OBSERVATIONAL_FIELDS.intersection(payload)
    if overlap:
        raise IdentityContractError(
            f"{name} excludes observational fields {sorted(overlap)}"
        )


def extract_existing_at1_identity_fields(
    payload: Mapping[str, Any],
    *,
    function_capsule_cid: str | None = None,
) -> dict[str, str]:
    """Read declared identity CIDs from an existing @1 payload.

    Extra non-observational fields are ignored so capsule ``@1`` identity
    payloads and ``to_dict`` envelopes remain readable.  The input mapping is
    never mutated.  ``function_capsule_cid`` may be supplied when the source
    identity payload omits its derived aggregate.
    """

    if not isinstance(payload, Mapping) or isinstance(payload, (str, bytes, bytearray)):
        raise IdentityContractError("existing @1 payload must be a mapping")
    _reject_observational(payload, "existing @1 payload")
    extracted: dict[str, str] = {}
    missing: list[str] = []
    for name in EXISTING_AT1_IDENTITY_DIMENSIONS:
        if name not in payload:
            missing.append(name)
            continue
        extracted[name] = _cid(payload[name], name)
    if missing:
        raise IdentityContractError(
            "existing @1 payload is missing identity fields "
            f"{missing}"
        )
    claimed = payload.get("function_capsule_cid", function_capsule_cid)
    if claimed is None:
        raise IdentityContractError(
            "existing @1 payload requires function_capsule_cid or an explicit aggregate"
        )
    extracted["function_capsule_cid"] = _cid(claimed, "function_capsule_cid")
    return {name: extracted[name] for name in IDENTITY_FIELDS}


def present_existing_at1_identity_fields(
    payload: Mapping[str, Any],
) -> dict[str, str]:
    """Extract any declared identity CIDs present on an existing @1 payload."""

    if not isinstance(payload, Mapping) or isinstance(payload, (str, bytes, bytearray)):
        raise IdentityContractError("existing @1 payload must be a mapping")
    _reject_observational(payload, "existing @1 payload")
    extracted: dict[str, str] = {}
    for name in IDENTITY_FIELDS:
        if name in payload:
            extracted[name] = _cid(payload[name], name)
    return extracted


@dataclass(frozen=True, slots=True)
class SemanticArtifactIdentitySet:
    """Closed identity set separating implementation from binding/compatibility."""

    SCHEMA: ClassVar[str] = SEMANTIC_ARTIFACT_IDENTITY_SET_SCHEMA
    INTERFACE: ClassVar[str] = SEMANTIC_ARTIFACT_IDENTITY_SET_INTERFACE
    AGGREGATE_FIELD: ClassVar[str] = "identity_set_cid"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"schema", *IDENTITY_FIELDS, "identity_set_cid"}
    )
    _IDENTITY_FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", *IDENTITY_FIELDS})

    stable_symbol_id: str
    source_cid: str
    cst_cid: str
    ast_cid: str
    implementation_ir_cid: str
    symbol_binding_cid: str
    interface_contract_cid: str
    effect_summary_cid: str
    state_footprint_cid: str
    dependency_slice_cid: str
    behavior_summary_cid: str
    initialization_dependency_cid: str
    public_compatibility_cid: str
    validation_profile_cid: str
    provenance_cid: str
    semantic_state_root_cid: str
    function_capsule_cid: str

    def __post_init__(self) -> None:
        for name in IDENTITY_FIELDS:
            object.__setattr__(self, name, _cid(getattr(self, name), name))

    def identity_payload(self) -> dict[str, Any]:
        payload = {"schema": self.SCHEMA}
        for name in IDENTITY_FIELDS:
            payload[name] = getattr(self, name)
        _require_dag_json(payload, type(self).__name__)
        return payload

    @property
    def identity_set_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload[self.AGGREGATE_FIELD] = self.identity_set_cid
        return payload

    def field(self, name: str) -> str:
        spec = classify_identity_field(name)
        return str(getattr(self, spec.name))

    def identities_for(
        self,
        names: Sequence[str],
    ) -> dict[str, str]:
        return {name: self.field(name) for name in names}

    def location_independent_identities(self) -> dict[str, str]:
        return self.identities_for(LOCATION_INDEPENDENT_IDENTITY_FIELDS)

    def location_sensitive_identities(self) -> dict[str, str]:
        return self.identities_for(LOCATION_SENSITIVE_IDENTITY_FIELDS)

    def implementation_identity(self) -> dict[str, str]:
        return self.identities_for(IMPLEMENTATION_IDENTITY_FIELDS)

    def binding_identity(self) -> dict[str, str]:
        return self.identities_for(BINDING_IDENTITY_FIELDS)

    def contract_identity(self) -> dict[str, str]:
        return self.identities_for(CONTRACT_IDENTITY_FIELDS)

    def effect_identity(self) -> dict[str, str]:
        return self.identities_for(EFFECT_IDENTITY_FIELDS)

    def state_identity(self) -> dict[str, str]:
        return self.identities_for(STATE_IDENTITY_FIELDS)

    def dependency_identity(self) -> dict[str, str]:
        return self.identities_for(DEPENDENCY_IDENTITY_FIELDS)

    def behavior_identity(self) -> dict[str, str]:
        return self.identities_for(BEHAVIOR_IDENTITY_FIELDS)

    def validation_identity(self) -> dict[str, str]:
        return self.identities_for(VALIDATION_IDENTITY_FIELDS)

    def compatibility_identity(self) -> dict[str, str]:
        return self.identities_for(COMPATIBILITY_IDENTITY_FIELDS)

    def implementation_and_contract_identity(self) -> dict[str, str]:
        return self.identities_for(IMPLEMENTATION_AND_CONTRACT_IDENTITY_FIELDS)

    def binding_and_compatibility_identity(self) -> dict[str, str]:
        return self.identities_for(BINDING_AND_COMPATIBILITY_IDENTITY_FIELDS)

    def family_identities(self) -> dict[str, dict[str, str]]:
        return {
            family.value: self.identities_for(fields_for_family(family))
            for family in IdentityFamily
        }

    def replace(self, **changes: str) -> "SemanticArtifactIdentitySet":
        """Return a copy with named identity CIDs replaced."""

        overlap = FORBIDDEN_OBSERVATIONAL_FIELDS.intersection(changes)
        if overlap:
            raise IdentityContractError(
                f"replace excludes observational fields {sorted(overlap)}"
            )
        unknown = set(changes) - IDENTITY_FIELD_SET
        if unknown:
            raise IdentityContractError(
                f"replace rejects unknown identity fields {sorted(unknown)}"
            )
        payload = {name: getattr(self, name) for name in IDENTITY_FIELDS}
        payload.update(changes)
        return SemanticArtifactIdentitySet(**payload)

    def relocated(
        self,
        *,
        symbol_binding_cid: str,
        public_compatibility_cid: str,
        function_capsule_cid: str,
    ) -> "SemanticArtifactIdentitySet":
        """Move the artifact: preserve implementation, change binding/compat."""

        new_binding = _cid(symbol_binding_cid, "symbol_binding_cid")
        new_compat = _cid(public_compatibility_cid, "public_compatibility_cid")
        new_aggregate = _cid(function_capsule_cid, "function_capsule_cid")
        if new_binding == self.symbol_binding_cid:
            raise IdentityContractError("relocation must change symbol_binding_cid")
        if new_compat == self.public_compatibility_cid:
            raise IdentityContractError(
                "relocation must change public_compatibility_cid"
            )
        if new_aggregate == self.function_capsule_cid:
            raise IdentityContractError("relocation must change function_capsule_cid")
        moved = self.replace(
            symbol_binding_cid=new_binding,
            public_compatibility_cid=new_compat,
            function_capsule_cid=new_aggregate,
        )
        if moved.location_independent_identities() != self.location_independent_identities():
            raise IdentityContractError(
                "relocation must preserve location-independent identity"
            )
        return moved

    @classmethod
    def from_identity_payload(
        cls, data: Mapping[str, Any]
    ) -> "SemanticArtifactIdentitySet":
        payload = _closed(data, cls._IDENTITY_FIELDS, cls.__name__)
        if payload.pop("schema") != cls.SCHEMA:
            raise IdentityContractError(
                "unsupported SemanticArtifactIdentitySet schema version"
            )
        return cls(**payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticArtifactIdentitySet":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop(cls.AGGREGATE_FIELD)
        result = cls.from_identity_payload(payload)
        if claimed != result.identity_set_cid:
            raise IdentityContractError(
                "SemanticArtifactIdentitySet identity_set_cid does not verify"
            )
        return result

    @classmethod
    def from_existing_at1(
        cls,
        payload: Mapping[str, Any],
        *,
        function_capsule_cid: str | None = None,
    ) -> "SemanticArtifactIdentitySet":
        """Project existing @1 identity fields into this adapter without rewrite."""

        extracted = extract_existing_at1_identity_fields(
            payload, function_capsule_cid=function_capsule_cid
        )
        return cls(**extracted)


def _coerce_identity_set(
    value: SemanticArtifactIdentitySet | Mapping[str, Any],
    name: str,
) -> SemanticArtifactIdentitySet:
    if isinstance(value, SemanticArtifactIdentitySet):
        return value
    if isinstance(value, Mapping):
        if "identity_set_cid" in value:
            return SemanticArtifactIdentitySet.from_dict(value)
        return SemanticArtifactIdentitySet.from_identity_payload(value)
    raise IdentityContractError(f"{name} must be a SemanticArtifactIdentitySet")


@dataclass(frozen=True, slots=True)
class IdentityDelta:
    """Explicit preserved/changed identity delta for one before/after pair."""

    SCHEMA: ClassVar[str] = IDENTITY_DELTA_SCHEMA
    INTERFACE: ClassVar[str] = IDENTITY_DELTA_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "preserved_fields",
            "changed_fields",
            "preserved_families",
            "changed_families",
            "delta_cid",
        }
    )
    _IDENTITY_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "preserved_fields",
            "changed_fields",
            "preserved_families",
            "changed_families",
        }
    )

    preserved_fields: Sequence[str]
    changed_fields: Sequence[str]

    def __post_init__(self) -> None:
        preserved = _unique_sorted_fields(list(self.preserved_fields), "preserved_fields")
        changed = _unique_sorted_fields(list(self.changed_fields), "changed_fields")
        overlap = set(preserved) & set(changed)
        if overlap:
            raise IdentityContractError(
                f"identity delta fields must be partitioned, overlap {sorted(overlap)}"
            )
        covered = set(preserved) | set(changed)
        if covered != IDENTITY_FIELD_SET:
            raise IdentityContractError(
                "identity delta must cover every declared identity field"
            )
        object.__setattr__(self, "preserved_fields", preserved)
        object.__setattr__(self, "changed_fields", changed)

    @property
    def preserved_families(self) -> tuple[str, ...]:
        return tuple(
            sorted({_FIELD_FAMILY[name] for name in self.preserved_fields})
        )

    @property
    def changed_families(self) -> tuple[str, ...]:
        return tuple(sorted({_FIELD_FAMILY[name] for name in self.changed_fields}))

    def identity_payload(self) -> dict[str, Any]:
        payload = {
            "schema": self.SCHEMA,
            "preserved_fields": list(self.preserved_fields),
            "changed_fields": list(self.changed_fields),
            "preserved_families": list(self.preserved_families),
            "changed_families": list(self.changed_families),
        }
        _require_dag_json(payload, type(self).__name__)
        return payload

    @property
    def delta_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["delta_cid"] = self.delta_cid
        return payload

    def is_semantic_preserving_relocation(self) -> bool:
        return set(self.preserved_fields) == set(
            LOCATION_INDEPENDENT_IDENTITY_FIELDS
        ) and set(self.changed_fields) == set(LOCATION_SENSITIVE_IDENTITY_FIELDS) | set(
            AGGREGATE_IDENTITY_FIELDS
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IdentityDelta":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("delta_cid")
        if payload.pop("schema") != cls.SCHEMA:
            raise IdentityContractError("unsupported IdentityDelta schema version")
        claimed_preserved_families = payload.pop("preserved_families")
        claimed_changed_families = payload.pop("changed_families")
        result = cls(
            preserved_fields=payload["preserved_fields"],
            changed_fields=payload["changed_fields"],
        )
        if list(result.preserved_families) != list(claimed_preserved_families):
            raise IdentityContractError("IdentityDelta preserved_families do not verify")
        if list(result.changed_families) != list(claimed_changed_families):
            raise IdentityContractError("IdentityDelta changed_families do not verify")
        if claimed != result.delta_cid:
            raise IdentityContractError("IdentityDelta delta_cid does not verify")
        return result


def compare_identity_sets(
    before: SemanticArtifactIdentitySet | Mapping[str, Any],
    after: SemanticArtifactIdentitySet | Mapping[str, Any],
) -> IdentityDelta:
    """Return the explicit identity delta between two closed identity sets."""

    left = _coerce_identity_set(before, "before")
    right = _coerce_identity_set(after, "after")
    preserved: list[str] = []
    changed: list[str] = []
    for name in IDENTITY_FIELDS:
        if getattr(left, name) == getattr(right, name):
            preserved.append(name)
        else:
            changed.append(name)
    return IdentityDelta(preserved_fields=preserved, changed_fields=changed)


def require_semantic_preserving_relocation(
    before: SemanticArtifactIdentitySet | Mapping[str, Any],
    after: SemanticArtifactIdentitySet | Mapping[str, Any],
) -> IdentityDelta:
    """Fail closed unless only binding, compatibility, and aggregate changed."""

    delta = compare_identity_sets(before, after)
    if not delta.is_semantic_preserving_relocation():
        raise IdentityContractError(
            "move is not a semantic-preserving relocation; "
            f"changed={list(delta.changed_fields)}"
        )
    return delta


def _validate_move_kind(kind: str, delta: IdentityDelta) -> None:
    required = _KIND_REQUIRED_CHANGED_FAMILIES[kind]
    actual = frozenset(delta.changed_families)
    if actual != required:
        raise IdentityContractError(
            f"{kind} must change families {sorted(required)}, got {sorted(actual)}"
        )
    if kind == IdentityMoveKind.SEMANTIC_PRESERVING_RELOCATION.value:
        if not delta.is_semantic_preserving_relocation():
            raise IdentityContractError(
                "semantic_preserving_relocation must preserve location-independent identity"
            )
        return
    edit_family = _KIND_EDIT_FAMILY[kind]
    forbidden = {
        IdentityFamily.BINDING.value,
        IdentityFamily.COMPATIBILITY.value,
    }
    if forbidden & actual:
        raise IdentityContractError(
            f"{kind} must not change binding or compatibility identity"
        )
    expected_changed = set(fields_for_family(edit_family)) | set(AGGREGATE_IDENTITY_FIELDS)
    if set(delta.changed_fields) != expected_changed:
        raise IdentityContractError(
            f"{kind} must change exactly {sorted(expected_changed)}"
        )


@dataclass(frozen=True, slots=True)
class IdentityMoveVector:
    """Golden or constructed before/after identity move with an explicit delta."""

    SCHEMA: ClassVar[str] = IDENTITY_MOVE_VECTOR_SCHEMA
    INTERFACE: ClassVar[str] = IDENTITY_MOVE_VECTOR_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "name",
            "kind",
            "before",
            "after",
            "preserved_fields",
            "changed_fields",
            "move_vector_cid",
        }
    )
    _IDENTITY_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "name",
            "kind",
            "before",
            "after",
            "preserved_fields",
            "changed_fields",
        }
    )

    name: str
    kind: IdentityMoveKind | str
    before: SemanticArtifactIdentitySet | Mapping[str, Any]
    after: SemanticArtifactIdentitySet | Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "name"))
        if self.name.startswith("/") or "\\" in self.name or self.name.startswith("~"):
            raise IdentityContractError("name must not be a local filesystem path")
        kind = _enum(self.kind, IdentityMoveKind, "kind")
        object.__setattr__(self, "kind", kind)
        before = _coerce_identity_set(self.before, "before")
        after = _coerce_identity_set(self.after, "after")
        if before.identity_set_cid == after.identity_set_cid:
            raise IdentityContractError("move vector before and after must differ")
        object.__setattr__(self, "before", before)
        object.__setattr__(self, "after", after)
        delta = compare_identity_sets(before, after)
        _validate_move_kind(kind, delta)

    @property
    def delta(self) -> IdentityDelta:
        return compare_identity_sets(self.before, self.after)

    def identity_payload(self) -> dict[str, Any]:
        delta = self.delta
        payload = {
            "schema": self.SCHEMA,
            "name": self.name,
            "kind": self.kind,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "preserved_fields": list(delta.preserved_fields),
            "changed_fields": list(delta.changed_fields),
        }
        _require_dag_json(payload, type(self).__name__)
        return payload

    @property
    def move_vector_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["move_vector_cid"] = self.move_vector_cid
        return payload

    @classmethod
    def from_identity_payload(cls, data: Mapping[str, Any]) -> "IdentityMoveVector":
        payload = _closed(data, cls._IDENTITY_FIELDS, cls.__name__)
        if payload.pop("schema") != cls.SCHEMA:
            raise IdentityContractError("unsupported IdentityMoveVector schema version")
        result = cls(
            name=payload["name"],
            kind=payload["kind"],
            before=payload["before"],
            after=payload["after"],
        )
        claimed_preserved = _unique_sorted_fields(
            payload["preserved_fields"], "preserved_fields"
        )
        claimed_changed = _unique_sorted_fields(
            payload["changed_fields"], "changed_fields"
        )
        if claimed_preserved != result.delta.preserved_fields:
            raise IdentityContractError(
                "IdentityMoveVector preserved_fields do not verify"
            )
        if claimed_changed != result.delta.changed_fields:
            raise IdentityContractError(
                "IdentityMoveVector changed_fields do not verify"
            )
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IdentityMoveVector":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("move_vector_cid")
        result = cls.from_identity_payload(payload)
        if claimed != result.move_vector_cid:
            raise IdentityContractError(
                "IdentityMoveVector move_vector_cid does not verify"
            )
        return result


def _labeled_identity_cids(label: str) -> dict[str, str]:
    return {
        name: cid_for_bytes(f"{label}:{name}".encode("utf-8")) for name in IDENTITY_FIELDS
    }


def _identity_set_from_label(label: str) -> SemanticArtifactIdentitySet:
    return SemanticArtifactIdentitySet(**_labeled_identity_cids(label))


def _edit_family_vector(
    *,
    name: str,
    kind: IdentityMoveKind,
    family: IdentityFamily,
) -> IdentityMoveVector:
    before = _identity_set_from_label(f"golden:{name}:before")
    changes = {
        field: cid_for_bytes(f"golden:{name}:after:{field}".encode("utf-8"))
        for field in fields_for_family(family)
    }
    changes["function_capsule_cid"] = cid_for_bytes(
        f"golden:{name}:after:function_capsule_cid".encode("utf-8")
    )
    after = before.replace(**changes)
    return IdentityMoveVector(name=name, kind=kind, before=before, after=after)


def build_golden_move_vectors() -> tuple[IdentityMoveVector, ...]:
    """Return the closed golden move-vector suite (deterministic, content-addressed)."""

    origin = _identity_set_from_label("golden:semantic_preserving_relocation:before")
    relocated = origin.relocated(
        symbol_binding_cid=cid_for_bytes(
            b"golden:semantic_preserving_relocation:after:symbol_binding_cid"
        ),
        public_compatibility_cid=cid_for_bytes(
            b"golden:semantic_preserving_relocation:after:public_compatibility_cid"
        ),
        function_capsule_cid=cid_for_bytes(
            b"golden:semantic_preserving_relocation:after:function_capsule_cid"
        ),
    )
    relocation = IdentityMoveVector(
        name="semantic_preserving_relocation",
        kind=IdentityMoveKind.SEMANTIC_PRESERVING_RELOCATION,
        before=origin,
        after=relocated,
    )
    edits = (
        _edit_family_vector(
            name="implementation_edit",
            kind=IdentityMoveKind.IMPLEMENTATION_EDIT,
            family=IdentityFamily.IMPLEMENTATION,
        ),
        _edit_family_vector(
            name="contract_edit",
            kind=IdentityMoveKind.CONTRACT_EDIT,
            family=IdentityFamily.CONTRACT,
        ),
        _edit_family_vector(
            name="effect_edit",
            kind=IdentityMoveKind.EFFECT_EDIT,
            family=IdentityFamily.EFFECT,
        ),
        _edit_family_vector(
            name="state_edit",
            kind=IdentityMoveKind.STATE_EDIT,
            family=IdentityFamily.STATE,
        ),
        _edit_family_vector(
            name="dependency_edit",
            kind=IdentityMoveKind.DEPENDENCY_EDIT,
            family=IdentityFamily.DEPENDENCY,
        ),
        _edit_family_vector(
            name="behavior_edit",
            kind=IdentityMoveKind.BEHAVIOR_EDIT,
            family=IdentityFamily.BEHAVIOR,
        ),
        _edit_family_vector(
            name="validation_edit",
            kind=IdentityMoveKind.VALIDATION_EDIT,
            family=IdentityFamily.VALIDATION,
        ),
    )
    return (relocation, *edits)


GOLDEN_MOVE_VECTORS: Final[tuple[IdentityMoveVector, ...]] = build_golden_move_vectors()


def encode_canonical_identity_set(record: SemanticArtifactIdentitySet) -> bytes:
    """Return strict canonical DAG-JSON bytes of the identity payload."""

    if type(record) is not SemanticArtifactIdentitySet:
        raise IdentityContractError("encode requires a SemanticArtifactIdentitySet@1 record")
    data = record.canonical_bytes()
    if canonical_dag_json_bytes(json.loads(data.decode("utf-8"))) != data:
        raise IdentityContractError("identity encoding is not canonical")
    return data


def decode_canonical_identity_set(data: bytes) -> SemanticArtifactIdentitySet:
    """Decode canonical identity bytes; reject any non-normalized payload."""

    if type(data) is not bytes:
        raise IdentityContractError("canonical identity bytes must be exact bytes")
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise IdentityContractError("canonical identity bytes must be UTF-8 JSON") from exc
    if canonical_dag_json_bytes(payload) != data:
        raise IdentityContractError("identity bytes are not canonical DAG-JSON")
    result = SemanticArtifactIdentitySet.from_identity_payload(payload)
    if result.canonical_bytes() != data:
        raise IdentityContractError(
            "identity bytes are not the normalized identity payload"
        )
    return result


def encode_canonical_move_vector(record: IdentityMoveVector) -> bytes:
    """Return strict canonical DAG-JSON bytes of a move vector."""

    if type(record) is not IdentityMoveVector:
        raise IdentityContractError("encode requires an IdentityMoveVector@1 record")
    data = record.canonical_bytes()
    if canonical_dag_json_bytes(json.loads(data.decode("utf-8"))) != data:
        raise IdentityContractError("move vector encoding is not canonical")
    return data


def decode_canonical_move_vector(data: bytes) -> IdentityMoveVector:
    """Decode canonical move-vector bytes; reject any non-normalized payload."""

    if type(data) is not bytes:
        raise IdentityContractError("canonical move vector bytes must be exact bytes")
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise IdentityContractError(
            "canonical move vector bytes must be UTF-8 JSON"
        ) from exc
    if canonical_dag_json_bytes(payload) != data:
        raise IdentityContractError("move vector bytes are not canonical DAG-JSON")
    result = IdentityMoveVector.from_identity_payload(payload)
    if result.canonical_bytes() != data:
        raise IdentityContractError(
            "move vector bytes are not the normalized identity payload"
        )
    return result


def provider_free_exports() -> tuple[str, ...]:
    """Return the sorted public export surface (no provider or model names)."""

    return tuple(sorted(__all__))


__all__ = [
    "AGGREGATE_IDENTITY_FIELDS",
    "AUTHORITY",
    "AUTHORITY_OWNER",
    "BEHAVIOR_IDENTITY_FIELDS",
    "BINDING_AND_COMPATIBILITY_IDENTITY_FIELDS",
    "BINDING_IDENTITY_FIELDS",
    "COMPATIBILITY_IDENTITY_FIELDS",
    "CONTRACT_IDENTITY_FIELDS",
    "DEPENDENCY_IDENTITY_FIELDS",
    "DUCKLAKE_IS_AUTHORITY",
    "EFFECT_IDENTITY_FIELDS",
    "EXISTING_AT1_IDENTITY_DIMENSIONS",
    "FORBIDDEN_OBSERVATIONAL_FIELDS",
    "GOAL_ID",
    "GOLDEN_MOVE_VECTORS",
    "IDENTITIES_CAN_AUTHORIZE_COMPLETION",
    "IDENTITIES_CAN_AUTHORIZE_TRANSITION",
    "IDENTITIES_CAN_CREATE_AUTHORITY",
    "IDENTITY_CID_CODEC",
    "IDENTITY_CID_PROFILE",
    "IDENTITY_CONTRACT_VERSION",
    "IDENTITY_DELTA_INTERFACE",
    "IDENTITY_DELTA_SCHEMA",
    "IDENTITY_FIELDS",
    "IDENTITY_FIELD_SET",
    "IDENTITY_FIELD_SPECS",
    "IDENTITY_MOVE_VECTOR_INTERFACE",
    "IDENTITY_MOVE_VECTOR_SCHEMA",
    "IMPLEMENTATION_AND_CONTRACT_IDENTITY_FIELDS",
    "IMPLEMENTATION_IDENTITY_FIELDS",
    "LOCATION_INDEPENDENT_IDENTITY_FIELDS",
    "LOCATION_SENSITIVE_IDENTITY_FIELDS",
    "MARKDOWN_IS_NOT_COMPLETION",
    "MODEL_OUTPUT_IS_PROPOSAL_ONLY",
    "PRIMARY_IDENTITY_FAMILIES",
    "PROGRAM",
    "SEMANTIC_ARTIFACT_IDENTITY_SET_INTERFACE",
    "SEMANTIC_ARTIFACT_IDENTITY_SET_SCHEMA",
    "STATE_IDENTITY_FIELDS",
    "TASK_ID",
    "TEST_PASS_IS_NOT_COMPLETION",
    "VALIDATION_IDENTITY_FIELDS",
    "VECTOR_SIMILARITY_IS_AUTHORITY",
    "WORKER_SELF_APPROVAL",
    "IdentityContractError",
    "IdentityDelta",
    "IdentityFamily",
    "IdentityFieldSpec",
    "IdentityMoveKind",
    "IdentityMoveVector",
    "IdentitySensitivity",
    "SemanticArtifactIdentitySet",
    "build_golden_move_vectors",
    "classify_identity_field",
    "compare_identity_sets",
    "decode_canonical_identity_set",
    "decode_canonical_move_vector",
    "encode_canonical_identity_set",
    "encode_canonical_move_vector",
    "extract_existing_at1_identity_fields",
    "fields_for_family",
    "fields_for_sensitivity",
    "identity_cid_profile",
    "is_forbidden_observational_field",
    "present_existing_at1_identity_fields",
    "provider_free_exports",
    "require_semantic_preserving_relocation",
]
