"""VerificationPolicy and VerificationRequirementManifest schemas (IPS-009).

Datasets semantic authority for the required-unit set.  The manifest binds
repository/revision/source root, exact sorted required unit IDs and unit
descriptor CIDs, policy and selector CIDs, environment and lock CIDs,
schema/canonicalization/graph versions, permitted removals with current-policy
authorization, logical epoch, and the content-addressed manifest root.

Rules:

* added selected units are always required for seal;
* unauthorized disappearance of a required unit fails closed;
* the manifest root changes for every required-set, policy, selector, or
  context mutation;
* duplicate IDs or non-canonical order are rejected, never silently normalized;
* imports have no side effects (CID minting reuses identity helpers lazily).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from .evidence import EvidenceClassError, ProofUnitKind, parse_proof_unit_kind
from .identity import (
    ABSENCE_TOKEN,
    CANONICALIZATION_VERSION,
    SECRET_AND_NONDETERMINISTIC_FIELDS,
    IdentityError,
    canonical_cid,
    validate_profile_cid,
)

MANIFEST_SUBSET: Final[str] = "ips/verification-manifest@1"
MANIFEST_NAMESPACE: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/manifest"
)
SCHEMA_MAJOR: Final[int] = 1
PROOF_SCHEMA_VERSION: Final[str] = str(SCHEMA_MAJOR)
TYPED_ABSENCE: Final[str] = "typed_absence"
MAX_IDENTIFIER_BYTES: Final[int] = 512
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1

VERIFICATION_POLICY_SCHEMA: Final[str] = (
    f"{MANIFEST_NAMESPACE}/verification-policy@{SCHEMA_MAJOR}"
)
REQUIRED_UNIT_DESCRIPTOR_SCHEMA: Final[str] = (
    f"{MANIFEST_NAMESPACE}/required-unit-descriptor@{SCHEMA_MAJOR}"
)
UNIT_REMOVAL_AUTHORIZATION_SCHEMA: Final[str] = (
    f"{MANIFEST_NAMESPACE}/unit-removal-authorization@{SCHEMA_MAJOR}"
)
VERIFICATION_REQUIREMENT_MANIFEST_SCHEMA: Final[str] = (
    f"{MANIFEST_NAMESPACE}/verification-requirement-manifest@{SCHEMA_MAJOR}"
)

# Selection sources that force required_for_seal=True when admitted.
_SELECTED_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "selected_test",
        "selected_property",
        "selected_unit",
        "policy_selected",
        "discovery_selected",
    }
)

# Closed removal reason codes.
CLOSED_REMOVAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "test_deleted",
        "property_deleted",
        "unit_superseded",
        "selector_deselected",
        "policy_exempted",
        "tombstone",
    }
)


class ManifestError(ValueError):
    """Verification policy or requirement-manifest contract violation."""


def _is_absence(value: Any) -> bool:
    return value == ABSENCE_TOKEN


def _require_text(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and _is_absence(value):
        return ABSENCE_TOKEN
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{field} must be a non-empty string or {ABSENCE_TOKEN}")
    text = value.strip()
    if text != value:
        raise ManifestError(f"{field} must not have surrounding whitespace")
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise ManifestError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_cid(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and _is_absence(value):
        return ABSENCE_TOKEN
    text = _require_text(value, field, allow_absence=False)
    try:
        return validate_profile_cid(text, domain="any")
    except IdentityError as exc:
        raise ManifestError(f"{field}: {exc}") from exc


def _require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ManifestError(f"{field} must be a boolean")
    return value


def _require_nonneg_int(value: Any, field: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise ManifestError(f"{field} must be a finite int")
    if value < 0 or value > MAX_SAFE_INTEGER:
        raise ManifestError(f"{field} is out of bounds")
    return value


def _require_positive_int(value: Any, field: str) -> int:
    number = _require_nonneg_int(value, field)
    if number < 1:
        raise ManifestError(f"{field} must be >= 1")
    return number


def _reject_secret_fields(payload: Mapping[str, Any]) -> None:
    leaked = set(payload) & SECRET_AND_NONDETERMINISTIC_FIELDS
    if leaked:
        raise ManifestError(
            f"secret or nondeterministic fields are forbidden: {sorted(leaked)}"
        )


def _seq_canonical(values: Sequence[str]) -> list[str] | str:
    return list(values) if values else ABSENCE_TOKEN


def _parse_kind(value: Any) -> ProofUnitKind:
    try:
        return parse_proof_unit_kind(value)
    except EvidenceClassError as exc:
        raise ManifestError(str(exc)) from exc


def _require_sorted_unique_strings(
    value: Any, field: str, *, allow_absence: bool = True
) -> tuple[str, ...]:
    if allow_absence and _is_absence(value):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ManifestError(f"{field} must be a sequence or {ABSENCE_TOKEN}")
    items = tuple(_require_text(item, field, allow_absence=False) for item in value)
    if list(items) != sorted(items):
        raise ManifestError(f"{field} must be canonically sorted")
    if len(set(items)) != len(items):
        raise ManifestError(f"{field} must not contain duplicates")
    return items


# ---------------------------------------------------------------------------
# VerificationPolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    """Closed verification and seal-transition policy controls.

    Encodes required-set completeness expectations, removal authorization
    gates, and periodic/full-checkpoint triggers.  Content-addressed via
    :meth:`policy_cid`.
    """

    policy_id: str
    require_removal_authorization: bool
    allow_selected_unit_omission: bool
    full_checkpoint_every_n_commits: int
    max_delta_chain_depth: int
    min_reuse_ratio_basis_points: int
    require_full_on_environment_change: bool
    require_full_on_circuit_or_key_change: bool
    require_full_on_schema_or_canonicalization_change: bool
    require_full_on_dependency_lock_change: bool
    require_full_on_trust_policy_change: bool
    require_full_on_release_qualification: bool
    permitted_removal_reasons: tuple[str, ...]
    permitted_risk_classes_for_removal: tuple[str, ...]
    canonicalization_version: str = CANONICALIZATION_VERSION
    proof_schema_version: str = PROOF_SCHEMA_VERSION
    schema: str = VERIFICATION_POLICY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_id", _require_text(self.policy_id, "policy_id")
        )
        object.__setattr__(
            self,
            "require_removal_authorization",
            _require_bool(
                self.require_removal_authorization, "require_removal_authorization"
            ),
        )
        object.__setattr__(
            self,
            "allow_selected_unit_omission",
            _require_bool(
                self.allow_selected_unit_omission, "allow_selected_unit_omission"
            ),
        )
        if self.allow_selected_unit_omission:
            raise ManifestError(
                "allow_selected_unit_omission must be false; "
                "added selected units are always required"
            )
        if not self.require_removal_authorization:
            raise ManifestError(
                "require_removal_authorization must be true; "
                "deleted required units need current-policy authorization"
            )
        object.__setattr__(
            self,
            "full_checkpoint_every_n_commits",
            _require_positive_int(
                self.full_checkpoint_every_n_commits,
                "full_checkpoint_every_n_commits",
            ),
        )
        object.__setattr__(
            self,
            "max_delta_chain_depth",
            _require_positive_int(
                self.max_delta_chain_depth, "max_delta_chain_depth"
            ),
        )
        object.__setattr__(
            self,
            "min_reuse_ratio_basis_points",
            _require_nonneg_int(
                self.min_reuse_ratio_basis_points, "min_reuse_ratio_basis_points"
            ),
        )
        if self.min_reuse_ratio_basis_points > 10000:
            raise ManifestError("min_reuse_ratio_basis_points must be <= 10000")
        for field in (
            "require_full_on_environment_change",
            "require_full_on_circuit_or_key_change",
            "require_full_on_schema_or_canonicalization_change",
            "require_full_on_dependency_lock_change",
            "require_full_on_trust_policy_change",
            "require_full_on_release_qualification",
        ):
            object.__setattr__(
                self, field, _require_bool(getattr(self, field), field)
            )
        reasons = _require_sorted_unique_strings(
            self.permitted_removal_reasons, "permitted_removal_reasons"
        )
        unknown_reasons = sorted(set(reasons) - CLOSED_REMOVAL_REASONS)
        if unknown_reasons:
            raise ManifestError(
                f"unknown removal reasons: {unknown_reasons}; closed set is "
                f"{sorted(CLOSED_REMOVAL_REASONS)}"
            )
        object.__setattr__(self, "permitted_removal_reasons", reasons)
        object.__setattr__(
            self,
            "permitted_risk_classes_for_removal",
            _require_sorted_unique_strings(
                self.permitted_risk_classes_for_removal,
                "permitted_risk_classes_for_removal",
            ),
        )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_text(self.canonicalization_version, "canonicalization_version"),
        )
        object.__setattr__(
            self,
            "proof_schema_version",
            _require_text(
                self.proof_schema_version, "proof_schema_version", allow_absence=False
            ),
        )
        object.__setattr__(
            self, "schema", _require_text(self.schema, "schema", allow_absence=False)
        )
        if self.schema != VERIFICATION_POLICY_SCHEMA:
            raise ManifestError(
                f"verification policy schema must be {VERIFICATION_POLICY_SCHEMA}"
            )

    def authorizes_removal(
        self,
        *,
        reason: str,
        risk_class: str,
        policy_cid: str,
    ) -> bool:
        """Return True when this policy admits a removal under current binding."""

        if not self.require_removal_authorization:
            return False
        if reason not in self.permitted_removal_reasons:
            return False
        if (
            self.permitted_risk_classes_for_removal
            and risk_class not in self.permitted_risk_classes_for_removal
        ):
            return False
        # Caller must bind the live policy CID; mismatched binding fails.
        return policy_cid == self.policy_cid()

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "manifest_subset": MANIFEST_SUBSET,
            "policy_id": self.policy_id,
            "require_removal_authorization": self.require_removal_authorization,
            "allow_selected_unit_omission": self.allow_selected_unit_omission,
            "full_checkpoint_every_n_commits": self.full_checkpoint_every_n_commits,
            "max_delta_chain_depth": self.max_delta_chain_depth,
            "min_reuse_ratio_basis_points": self.min_reuse_ratio_basis_points,
            "require_full_on_environment_change": (
                self.require_full_on_environment_change
            ),
            "require_full_on_circuit_or_key_change": (
                self.require_full_on_circuit_or_key_change
            ),
            "require_full_on_schema_or_canonicalization_change": (
                self.require_full_on_schema_or_canonicalization_change
            ),
            "require_full_on_dependency_lock_change": (
                self.require_full_on_dependency_lock_change
            ),
            "require_full_on_trust_policy_change": (
                self.require_full_on_trust_policy_change
            ),
            "require_full_on_release_qualification": (
                self.require_full_on_release_qualification
            ),
            "permitted_removal_reasons": _seq_canonical(
                self.permitted_removal_reasons
            ),
            "permitted_risk_classes_for_removal": _seq_canonical(
                self.permitted_risk_classes_for_removal
            ),
            "canonicalization_version": self.canonicalization_version,
            "proof_schema_version": self.proof_schema_version,
            "typed_absence": TYPED_ABSENCE,
        }

    def to_canonical_json(self) -> str:
        payload = self.to_canonical()
        _reject_secret_fields(payload)
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def policy_cid(self) -> str:
        return canonical_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> VerificationPolicy:
        if not isinstance(payload, Mapping):
            raise ManifestError("VerificationPolicy payload must be a mapping")
        _reject_secret_fields(payload)
        schema = payload.get("schema", VERIFICATION_POLICY_SCHEMA)
        if schema != VERIFICATION_POLICY_SCHEMA:
            raise ManifestError(
                f"unsupported VerificationPolicy schema {schema!r}; "
                f"expected {VERIFICATION_POLICY_SCHEMA}"
            )
        return cls(
            policy_id=payload.get("policy_id", ""),
            require_removal_authorization=payload.get(
                "require_removal_authorization"
            ),
            allow_selected_unit_omission=payload.get("allow_selected_unit_omission"),
            full_checkpoint_every_n_commits=payload.get(
                "full_checkpoint_every_n_commits"
            ),
            max_delta_chain_depth=payload.get("max_delta_chain_depth"),
            min_reuse_ratio_basis_points=payload.get(
                "min_reuse_ratio_basis_points"
            ),
            require_full_on_environment_change=payload.get(
                "require_full_on_environment_change"
            ),
            require_full_on_circuit_or_key_change=payload.get(
                "require_full_on_circuit_or_key_change"
            ),
            require_full_on_schema_or_canonicalization_change=payload.get(
                "require_full_on_schema_or_canonicalization_change"
            ),
            require_full_on_dependency_lock_change=payload.get(
                "require_full_on_dependency_lock_change"
            ),
            require_full_on_trust_policy_change=payload.get(
                "require_full_on_trust_policy_change"
            ),
            require_full_on_release_qualification=payload.get(
                "require_full_on_release_qualification"
            ),
            permitted_removal_reasons=payload.get(
                "permitted_removal_reasons", ABSENCE_TOKEN
            ),
            permitted_risk_classes_for_removal=payload.get(
                "permitted_risk_classes_for_removal", ABSENCE_TOKEN
            ),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
            proof_schema_version=str(
                payload.get("proof_schema_version") or PROOF_SCHEMA_VERSION
            ),
            schema=str(schema),
        )


# ---------------------------------------------------------------------------
# RequiredUnitDescriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequiredUnitDescriptor:
    """One required proof unit bound into a verification requirement manifest.

    Selected units always carry ``required_for_seal=True``.  Descriptors are
    ordered by ``proof_unit_id`` inside a manifest.
    """

    proof_unit_id: str
    unit_descriptor_cid: str
    proof_unit_kind: ProofUnitKind
    selection_source: str
    risk_class: str
    required_for_seal: bool = True
    schema: str = REQUIRED_UNIT_DESCRIPTOR_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proof_unit_id",
            _require_text(self.proof_unit_id, "proof_unit_id"),
        )
        object.__setattr__(
            self,
            "unit_descriptor_cid",
            _require_cid(self.unit_descriptor_cid, "unit_descriptor_cid"),
        )
        object.__setattr__(self, "proof_unit_kind", _parse_kind(self.proof_unit_kind))
        object.__setattr__(
            self,
            "selection_source",
            _require_text(self.selection_source, "selection_source"),
        )
        object.__setattr__(
            self, "risk_class", _require_text(self.risk_class, "risk_class")
        )
        object.__setattr__(
            self,
            "required_for_seal",
            _require_bool(self.required_for_seal, "required_for_seal"),
        )
        if self.selection_source in _SELECTED_SOURCES and not self.required_for_seal:
            raise ManifestError(
                "added selected units are required; required_for_seal must be true"
            )
        if not self.required_for_seal:
            raise ManifestError(
                "RequiredUnitDescriptor admits only required_for_seal=true units"
            )
        object.__setattr__(
            self, "schema", _require_text(self.schema, "schema", allow_absence=False)
        )
        if self.schema != REQUIRED_UNIT_DESCRIPTOR_SCHEMA:
            raise ManifestError(
                f"required unit descriptor schema must be "
                f"{REQUIRED_UNIT_DESCRIPTOR_SCHEMA}"
            )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "proof_unit_id": self.proof_unit_id,
            "unit_descriptor_cid": self.unit_descriptor_cid,
            "proof_unit_kind": self.proof_unit_kind.value,
            "selection_source": self.selection_source,
            "risk_class": self.risk_class,
            "required_for_seal": self.required_for_seal,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def descriptor_cid(self) -> str:
        return canonical_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> RequiredUnitDescriptor:
        if not isinstance(payload, Mapping):
            raise ManifestError("RequiredUnitDescriptor payload must be a mapping")
        _reject_secret_fields(payload)
        return cls(
            proof_unit_id=str(payload.get("proof_unit_id") or ""),
            unit_descriptor_cid=str(payload.get("unit_descriptor_cid") or ""),
            proof_unit_kind=payload.get("proof_unit_kind") or "",
            selection_source=str(payload.get("selection_source") or ""),
            risk_class=str(payload.get("risk_class") or ""),
            required_for_seal=payload.get("required_for_seal", True),
            schema=str(
                payload.get("schema") or REQUIRED_UNIT_DESCRIPTOR_SCHEMA
            ),
        )

    @classmethod
    def from_selected(
        cls,
        *,
        proof_unit_id: str,
        unit_descriptor_cid: str,
        proof_unit_kind: ProofUnitKind | str,
        selection_source: str = "selected_unit",
        risk_class: str = "high",
    ) -> RequiredUnitDescriptor:
        """Mint a required descriptor for a newly selected unit."""

        source = selection_source
        if source not in _SELECTED_SOURCES:
            source = "selected_unit"
        return cls(
            proof_unit_id=proof_unit_id,
            unit_descriptor_cid=unit_descriptor_cid,
            proof_unit_kind=proof_unit_kind,
            selection_source=source,
            risk_class=risk_class,
            required_for_seal=True,
        )


# ---------------------------------------------------------------------------
# UnitRemovalAuthorization
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnitRemovalAuthorization:
    """Current-policy authorization for removing one previously required unit.

    Unauthorized disappearance fails closed; every deleted required unit needs
    an explicit record bound to the live policy CID.
    """

    proof_unit_id: str
    policy_cid: str
    removal_reason: str
    risk_class: str
    tombstone_cid: str
    authorized: bool
    logical_epoch: int
    schema: str = UNIT_REMOVAL_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proof_unit_id",
            _require_text(self.proof_unit_id, "proof_unit_id"),
        )
        object.__setattr__(
            self, "policy_cid", _require_cid(self.policy_cid, "policy_cid")
        )
        object.__setattr__(
            self,
            "removal_reason",
            _require_text(self.removal_reason, "removal_reason"),
        )
        if self.removal_reason not in CLOSED_REMOVAL_REASONS:
            raise ManifestError(
                f"unknown removal reason {self.removal_reason!r}; closed set is "
                f"{sorted(CLOSED_REMOVAL_REASONS)}"
            )
        object.__setattr__(
            self, "risk_class", _require_text(self.risk_class, "risk_class")
        )
        object.__setattr__(
            self,
            "tombstone_cid",
            _require_cid(self.tombstone_cid, "tombstone_cid", allow_absence=True),
        )
        object.__setattr__(
            self, "authorized", _require_bool(self.authorized, "authorized")
        )
        if not self.authorized:
            raise ManifestError(
                "UnitRemovalAuthorization.authorized must be true; "
                "unauthorized disappearance fails"
            )
        object.__setattr__(
            self,
            "logical_epoch",
            _require_nonneg_int(self.logical_epoch, "logical_epoch"),
        )
        object.__setattr__(
            self, "schema", _require_text(self.schema, "schema", allow_absence=False)
        )
        if self.schema != UNIT_REMOVAL_AUTHORIZATION_SCHEMA:
            raise ManifestError(
                f"unit removal authorization schema must be "
                f"{UNIT_REMOVAL_AUTHORIZATION_SCHEMA}"
            )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "proof_unit_id": self.proof_unit_id,
            "policy_cid": self.policy_cid,
            "removal_reason": self.removal_reason,
            "risk_class": self.risk_class,
            "tombstone_cid": self.tombstone_cid,
            "authorized": self.authorized,
            "logical_epoch": self.logical_epoch,
            "typed_absence": TYPED_ABSENCE,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def authorization_cid(self) -> str:
        return canonical_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> UnitRemovalAuthorization:
        if not isinstance(payload, Mapping):
            raise ManifestError("UnitRemovalAuthorization payload must be a mapping")
        _reject_secret_fields(payload)
        return cls(
            proof_unit_id=str(payload.get("proof_unit_id") or ""),
            policy_cid=str(payload.get("policy_cid") or ""),
            removal_reason=str(payload.get("removal_reason") or ""),
            risk_class=str(payload.get("risk_class") or ""),
            tombstone_cid=str(payload.get("tombstone_cid") or ABSENCE_TOKEN),
            authorized=payload.get("authorized"),
            logical_epoch=payload.get("logical_epoch"),
            schema=str(
                payload.get("schema") or UNIT_REMOVAL_AUTHORIZATION_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# VerificationRequirementManifest
# ---------------------------------------------------------------------------


MANIFEST_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "repository_id",
    "revision",
    "repository_state_cid",
    "source_root_cid",
    "required_units",
    "policy_cid",
    "test_selector_cid",
    "environment_cid",
    "dependency_lock_cid",
    "configuration_cid",
    "network_policy_cid",
    "proof_schema_version",
    "canonicalization_version",
    "dependency_graph_schema_version",
    "permitted_removals",
    "logical_epoch",
)


def _sort_required_units(
    units: Sequence[RequiredUnitDescriptor],
) -> tuple[RequiredUnitDescriptor, ...]:
    if not isinstance(units, Sequence) or isinstance(units, (str, bytes)):
        raise ManifestError("required_units must be a sequence")
    ordered = tuple(units)
    ids = [unit.proof_unit_id for unit in ordered]
    if ids != sorted(ids):
        raise ManifestError("required_units must be canonically sorted by proof_unit_id")
    if len(set(ids)) != len(ids):
        raise ManifestError("required_units must not contain duplicate proof_unit_id")
    for unit in ordered:
        if not isinstance(unit, RequiredUnitDescriptor):
            raise ManifestError("required_units entries must be RequiredUnitDescriptor")
        if not unit.required_for_seal:
            raise ManifestError("every required unit must have required_for_seal=true")
    return ordered


def _sort_removals(
    removals: Sequence[UnitRemovalAuthorization],
) -> tuple[UnitRemovalAuthorization, ...]:
    if not isinstance(removals, Sequence) or isinstance(removals, (str, bytes)):
        raise ManifestError("permitted_removals must be a sequence")
    ordered = tuple(removals)
    ids = [item.proof_unit_id for item in ordered]
    if ids != sorted(ids):
        raise ManifestError(
            "permitted_removals must be canonically sorted by proof_unit_id"
        )
    if len(set(ids)) != len(ids):
        raise ManifestError(
            "permitted_removals must not contain duplicate proof_unit_id"
        )
    for item in ordered:
        if not isinstance(item, UnitRemovalAuthorization):
            raise ManifestError(
                "permitted_removals entries must be UnitRemovalAuthorization"
            )
        if not item.authorized:
            raise ManifestError("unauthorized disappearance fails")
    return ordered


@dataclass(frozen=True, slots=True)
class VerificationRequirementManifest:
    """Exact required-unit set for one repository seal epoch.

    The content-addressed :meth:`manifest_root` commits to the complete
    required set, policy, selector, and execution-context bindings.  Any
    mutation of those axes yields a different root.
    """

    repository_id: str
    revision: str
    repository_state_cid: str
    source_root_cid: str
    required_units: tuple[RequiredUnitDescriptor, ...]
    policy_cid: str
    test_selector_cid: str
    environment_cid: str
    dependency_lock_cid: str
    configuration_cid: str
    network_policy_cid: str
    proof_schema_version: str
    canonicalization_version: str
    dependency_graph_schema_version: str
    permitted_removals: tuple[UnitRemovalAuthorization, ...]
    logical_epoch: int
    schema: str = VERIFICATION_REQUIREMENT_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _require_text(self.repository_id, "repository_id"),
        )
        object.__setattr__(
            self, "revision", _require_text(self.revision, "revision")
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _require_cid(self.repository_state_cid, "repository_state_cid"),
        )
        object.__setattr__(
            self,
            "source_root_cid",
            _require_cid(self.source_root_cid, "source_root_cid"),
        )
        if self.source_root_cid == self.repository_state_cid:
            raise ManifestError(
                "source_root_cid is the repository source root, not "
                "repository_state_cid"
            )
        object.__setattr__(
            self, "required_units", _sort_required_units(self.required_units)
        )
        object.__setattr__(
            self, "policy_cid", _require_cid(self.policy_cid, "policy_cid")
        )
        object.__setattr__(
            self,
            "test_selector_cid",
            _require_cid(
                self.test_selector_cid, "test_selector_cid", allow_absence=True
            ),
        )
        object.__setattr__(
            self,
            "environment_cid",
            _require_cid(self.environment_cid, "environment_cid"),
        )
        object.__setattr__(
            self,
            "dependency_lock_cid",
            _require_cid(self.dependency_lock_cid, "dependency_lock_cid"),
        )
        object.__setattr__(
            self,
            "configuration_cid",
            _require_cid(self.configuration_cid, "configuration_cid"),
        )
        object.__setattr__(
            self,
            "network_policy_cid",
            _require_cid(
                self.network_policy_cid, "network_policy_cid", allow_absence=True
            ),
        )
        object.__setattr__(
            self,
            "proof_schema_version",
            _require_text(
                self.proof_schema_version, "proof_schema_version", allow_absence=False
            ),
        )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_text(self.canonicalization_version, "canonicalization_version"),
        )
        object.__setattr__(
            self,
            "dependency_graph_schema_version",
            _require_text(
                self.dependency_graph_schema_version,
                "dependency_graph_schema_version",
            ),
        )
        object.__setattr__(
            self,
            "permitted_removals",
            _sort_removals(self.permitted_removals),
        )
        # A unit cannot be both required and permitted-removed in one epoch.
        required_ids = {unit.proof_unit_id for unit in self.required_units}
        removed_ids = {item.proof_unit_id for item in self.permitted_removals}
        overlap = sorted(required_ids & removed_ids)
        if overlap:
            raise ManifestError(
                f"units cannot be both required and removed: {overlap}"
            )
        for removal in self.permitted_removals:
            if removal.policy_cid != self.policy_cid:
                raise ManifestError(
                    "removal authorization must bind the manifest policy_cid; "
                    f"{removal.proof_unit_id} has mismatched policy"
                )
        object.__setattr__(
            self,
            "logical_epoch",
            _require_nonneg_int(self.logical_epoch, "logical_epoch"),
        )
        object.__setattr__(
            self, "schema", _require_text(self.schema, "schema", allow_absence=False)
        )
        if self.schema != VERIFICATION_REQUIREMENT_MANIFEST_SCHEMA:
            raise ManifestError(
                f"manifest schema must be {VERIFICATION_REQUIREMENT_MANIFEST_SCHEMA}"
            )

    @property
    def required_unit_ids(self) -> tuple[str, ...]:
        return tuple(unit.proof_unit_id for unit in self.required_units)

    @property
    def unit_descriptor_cids(self) -> tuple[str, ...]:
        return tuple(unit.unit_descriptor_cid for unit in self.required_units)

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "manifest_subset": MANIFEST_SUBSET,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "repository_state_cid": self.repository_state_cid,
            "source_root_cid": self.source_root_cid,
            "required_units": (
                [unit.to_canonical() for unit in self.required_units]
                if self.required_units
                else ABSENCE_TOKEN
            ),
            "required_unit_ids": _seq_canonical(self.required_unit_ids),
            "unit_descriptor_cids": _seq_canonical(self.unit_descriptor_cids),
            "policy_cid": self.policy_cid,
            "test_selector_cid": self.test_selector_cid,
            "environment_cid": self.environment_cid,
            "dependency_lock_cid": self.dependency_lock_cid,
            "configuration_cid": self.configuration_cid,
            "network_policy_cid": self.network_policy_cid,
            "proof_schema_version": self.proof_schema_version,
            "canonicalization_version": self.canonicalization_version,
            "dependency_graph_schema_version": self.dependency_graph_schema_version,
            "permitted_removals": (
                [item.to_canonical() for item in self.permitted_removals]
                if self.permitted_removals
                else ABSENCE_TOKEN
            ),
            "logical_epoch": self.logical_epoch,
            "typed_absence": TYPED_ABSENCE,
        }

    def to_canonical_json(self) -> str:
        payload = self.to_canonical()
        _reject_secret_fields(payload)
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def manifest_root(self) -> str:
        """Content-addressed root of the complete requirement manifest."""

        return canonical_cid(self.to_canonical())

    # Compatibility aliases used by adjacent seal/forest layers.
    def manifest_cid(self) -> str:
        return self.manifest_root()

    @property
    def root(self) -> str:
        return self.manifest_root()

    def assert_required_set_complete(
        self, present_unit_ids: Iterable[str]
    ) -> None:
        """Fail closed when any required unit is absent from the present set."""

        present = set(present_unit_ids)
        missing = [unit_id for unit_id in self.required_unit_ids if unit_id not in present]
        if missing:
            raise ManifestError(
                f"incomplete required set; missing required units: {missing}"
            )

    def assert_selected_units_required(
        self, selected_unit_ids: Iterable[str]
    ) -> None:
        """Fail closed when a selected unit is not required for seal."""

        required = set(self.required_unit_ids)
        missing = sorted(
            unit_id for unit_id in selected_unit_ids if unit_id not in required
        )
        if missing:
            raise ManifestError(
                f"added selected units are required; missing from required set: "
                f"{missing}"
            )
        for unit in self.required_units:
            if unit.selection_source in _SELECTED_SOURCES and not unit.required_for_seal:
                raise ManifestError(
                    f"selected unit {unit.proof_unit_id} must be required_for_seal"
                )

    @classmethod
    def from_canonical(
        cls, payload: Mapping[str, Any]
    ) -> VerificationRequirementManifest:
        if not isinstance(payload, Mapping):
            raise ManifestError(
                "VerificationRequirementManifest payload must be a mapping"
            )
        _reject_secret_fields(payload)
        missing = [field for field in MANIFEST_REQUIRED_FIELDS if field not in payload]
        if missing:
            raise ManifestError(
                f"VerificationRequirementManifest missing required fields: {missing}"
            )
        schema = payload.get("schema", VERIFICATION_REQUIREMENT_MANIFEST_SCHEMA)
        if schema != VERIFICATION_REQUIREMENT_MANIFEST_SCHEMA:
            raise ManifestError(
                f"unsupported manifest schema {schema!r}; "
                f"expected {VERIFICATION_REQUIREMENT_MANIFEST_SCHEMA}"
            )
        raw_units = payload["required_units"]
        if _is_absence(raw_units):
            units: tuple[RequiredUnitDescriptor, ...] = ()
        else:
            if not isinstance(raw_units, Sequence) or isinstance(raw_units, (str, bytes)):
                raise ManifestError("required_units must be a sequence or n/a")
            units = tuple(
                RequiredUnitDescriptor.from_canonical(item) for item in raw_units
            )
        raw_removals = payload["permitted_removals"]
        if _is_absence(raw_removals):
            removals: tuple[UnitRemovalAuthorization, ...] = ()
        else:
            if not isinstance(raw_removals, Sequence) or isinstance(
                raw_removals, (str, bytes)
            ):
                raise ManifestError("permitted_removals must be a sequence or n/a")
            removals = tuple(
                UnitRemovalAuthorization.from_canonical(item) for item in raw_removals
            )
        return cls(
            repository_id=str(payload["repository_id"]),
            revision=str(payload["revision"]),
            repository_state_cid=str(payload["repository_state_cid"]),
            source_root_cid=str(payload["source_root_cid"]),
            required_units=units,
            policy_cid=str(payload["policy_cid"]),
            test_selector_cid=str(payload["test_selector_cid"]),
            environment_cid=str(payload["environment_cid"]),
            dependency_lock_cid=str(payload["dependency_lock_cid"]),
            configuration_cid=str(payload["configuration_cid"]),
            network_policy_cid=str(payload["network_policy_cid"]),
            proof_schema_version=str(payload["proof_schema_version"]),
            canonicalization_version=str(payload["canonicalization_version"]),
            dependency_graph_schema_version=str(
                payload["dependency_graph_schema_version"]
            ),
            permitted_removals=removals,
            logical_epoch=payload["logical_epoch"],
            schema=str(schema),
        )


def sample_verification_policy(**overrides: Any) -> VerificationPolicy:
    """Minimal production-oriented policy for tests and hermetic vectors."""

    payload: dict[str, Any] = {
        "policy_id": "policy/default-production",
        "require_removal_authorization": True,
        "allow_selected_unit_omission": False,
        "full_checkpoint_every_n_commits": 50,
        "max_delta_chain_depth": 32,
        "min_reuse_ratio_basis_points": 2500,
        "require_full_on_environment_change": True,
        "require_full_on_circuit_or_key_change": True,
        "require_full_on_schema_or_canonicalization_change": True,
        "require_full_on_dependency_lock_change": True,
        "require_full_on_trust_policy_change": True,
        "require_full_on_release_qualification": True,
        "permitted_removal_reasons": sorted(
            ["test_deleted", "selector_deselected", "tombstone"]
        ),
        "permitted_risk_classes_for_removal": sorted(["low", "medium"]),
        "canonicalization_version": CANONICALIZATION_VERSION,
        "proof_schema_version": PROOF_SCHEMA_VERSION,
    }
    payload.update(overrides)
    return VerificationPolicy.from_canonical(payload)


def _cid(label: str) -> str:
    return canonical_cid({"ips_manifest_sample": label, "v": SCHEMA_MAJOR})


def sample_required_unit(
    *,
    proof_unit_id: str = "unit/test-entry",
    selection_source: str = "selected_test",
    kind: ProofUnitKind | str = ProofUnitKind.UNIT_TEST,
    risk_class: str = "high",
    descriptor_label: str | None = None,
) -> RequiredUnitDescriptor:
    return RequiredUnitDescriptor.from_selected(
        proof_unit_id=proof_unit_id,
        unit_descriptor_cid=_cid(descriptor_label or f"descriptor:{proof_unit_id}"),
        proof_unit_kind=kind,
        selection_source=selection_source,
        risk_class=risk_class,
    )


def sample_verification_requirement_manifest(
    **overrides: Any,
) -> VerificationRequirementManifest:
    """Minimal complete manifest with one selected required unit."""

    policy = sample_verification_policy()
    units = (
        sample_required_unit(proof_unit_id="unit/a"),
        sample_required_unit(
            proof_unit_id="unit/b",
            kind=ProofUnitKind.FORMAL_OBLIGATION,
            selection_source="selected_property",
        ),
    )
    # Ensure sorted by proof_unit_id.
    units = tuple(sorted(units, key=lambda item: item.proof_unit_id))
    payload: dict[str, Any] = {
        "repository_id": "repo/datasets",
        "revision": "rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "repository_state_cid": _cid("repository-state"),
        "source_root_cid": _cid("source-root"),
        "required_units": [unit.to_canonical() for unit in units],
        "policy_cid": policy.policy_cid(),
        "test_selector_cid": _cid("test-selector"),
        "environment_cid": _cid("environment"),
        "dependency_lock_cid": _cid("lock"),
        "configuration_cid": _cid("config"),
        "network_policy_cid": ABSENCE_TOKEN,
        "proof_schema_version": PROOF_SCHEMA_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "dependency_graph_schema_version": "graph@1",
        "permitted_removals": ABSENCE_TOKEN,
        "logical_epoch": 1,
    }
    payload.update(overrides)
    if "required_units" in overrides and isinstance(
        overrides["required_units"], Sequence
    ):
        raw = overrides["required_units"]
        if raw and isinstance(raw[0], RequiredUnitDescriptor):
            payload["required_units"] = [unit.to_canonical() for unit in raw]
    if "permitted_removals" in overrides and isinstance(
        overrides["permitted_removals"], Sequence
    ):
        raw_rem = overrides["permitted_removals"]
        if raw_rem and isinstance(raw_rem[0], UnitRemovalAuthorization):
            payload["permitted_removals"] = [item.to_canonical() for item in raw_rem]
        elif raw_rem == () or raw_rem == []:
            payload["permitted_removals"] = ABSENCE_TOKEN
    return VerificationRequirementManifest.from_canonical(payload)


def build_verification_requirement_manifest(
    *,
    repository_id: str,
    revision: str,
    repository_state_cid: str,
    source_root_cid: str,
    required_units: Sequence[RequiredUnitDescriptor],
    policy: VerificationPolicy | str,
    test_selector_cid: str = ABSENCE_TOKEN,
    environment_cid: str,
    dependency_lock_cid: str,
    configuration_cid: str,
    network_policy_cid: str = ABSENCE_TOKEN,
    proof_schema_version: str = PROOF_SCHEMA_VERSION,
    canonicalization_version: str = CANONICALIZATION_VERSION,
    dependency_graph_schema_version: str = "graph@1",
    permitted_removals: Sequence[UnitRemovalAuthorization] = (),
    logical_epoch: int = 0,
    selected_unit_ids: Iterable[str] | None = None,
) -> VerificationRequirementManifest:
    """Construct a manifest, enforcing selected-unit completeness.

    Required units are sorted by ``proof_unit_id``.  Duplicate or reordered
    input fails closed.  When ``selected_unit_ids`` is provided, every selected
    id must appear in the required set.
    """

    if isinstance(policy, VerificationPolicy):
        policy_cid = policy.policy_cid()
    else:
        policy_cid = _require_cid(policy, "policy_cid")

    ordered = tuple(sorted(required_units, key=lambda unit: unit.proof_unit_id))
    # Reject caller-provided non-canonical order rather than silently accepting
    # a different sequence identity after sort: if the input was unsorted or
    # duplicated, fail when the sorted unique set would hide that.
    input_ids = [unit.proof_unit_id for unit in required_units]
    if len(set(input_ids)) != len(input_ids):
        raise ManifestError("required_units must not contain duplicate proof_unit_id")
    if list(input_ids) != sorted(input_ids):
        raise ManifestError(
            "required_units must be canonically sorted by proof_unit_id"
        )

    removal_ordered = tuple(
        sorted(permitted_removals, key=lambda item: item.proof_unit_id)
    )
    removal_ids = [item.proof_unit_id for item in permitted_removals]
    if len(set(removal_ids)) != len(removal_ids):
        raise ManifestError(
            "permitted_removals must not contain duplicate proof_unit_id"
        )
    if list(removal_ids) != sorted(removal_ids):
        raise ManifestError(
            "permitted_removals must be canonically sorted by proof_unit_id"
        )

    manifest = VerificationRequirementManifest(
        repository_id=repository_id,
        revision=revision,
        repository_state_cid=repository_state_cid,
        source_root_cid=source_root_cid,
        required_units=ordered,
        policy_cid=policy_cid,
        test_selector_cid=test_selector_cid,
        environment_cid=environment_cid,
        dependency_lock_cid=dependency_lock_cid,
        configuration_cid=configuration_cid,
        network_policy_cid=network_policy_cid,
        proof_schema_version=proof_schema_version,
        canonicalization_version=canonicalization_version,
        dependency_graph_schema_version=dependency_graph_schema_version,
        permitted_removals=removal_ordered,
        logical_epoch=logical_epoch,
    )
    if selected_unit_ids is not None:
        manifest.assert_selected_units_required(selected_unit_ids)
    return manifest


def assert_no_unauthorized_disappearance(
    previous: VerificationRequirementManifest,
    current: VerificationRequirementManifest,
    *,
    policy: VerificationPolicy | None = None,
) -> None:
    """Fail closed when a previously required unit vanishes without authorization.

    A unit may leave the required set only when ``current.permitted_removals``
    contains an authorized record for that unit bound to the current policy CID.
    When ``policy`` is supplied, the removal reason and risk class must also be
    admitted by that policy.
    """

    previous_ids = set(previous.required_unit_ids)
    current_ids = set(current.required_unit_ids)
    disappeared = sorted(previous_ids - current_ids)
    if not disappeared:
        return
    authorized = {
        item.proof_unit_id: item
        for item in current.permitted_removals
        if item.authorized and item.policy_cid == current.policy_cid
    }
    unauthorized: list[str] = []
    for unit_id in disappeared:
        record = authorized.get(unit_id)
        if record is None:
            unauthorized.append(unit_id)
            continue
        if policy is not None:
            if not policy.authorizes_removal(
                reason=record.removal_reason,
                risk_class=record.risk_class,
                policy_cid=current.policy_cid,
            ):
                unauthorized.append(unit_id)
    if unauthorized:
        raise ManifestError(
            f"unauthorized disappearance of required units: {unauthorized}"
        )


def known_vectors() -> dict[str, Any]:
    """Versioned hermetic vectors for required-set and root-mutation regression."""

    policy = sample_verification_policy()
    base = sample_verification_requirement_manifest(policy_cid=policy.policy_cid())
    base_root = base.manifest_root()

    # Add a selected unit: must be required and must change the root.
    added_unit = sample_required_unit(
        proof_unit_id="unit/c",
        selection_source="selected_test",
    )
    with_added = build_verification_requirement_manifest(
        repository_id=base.repository_id,
        revision=base.revision,
        repository_state_cid=base.repository_state_cid,
        source_root_cid=base.source_root_cid,
        required_units=tuple(
            sorted(
                list(base.required_units) + [added_unit],
                key=lambda item: item.proof_unit_id,
            )
        ),
        policy=base.policy_cid,
        test_selector_cid=base.test_selector_cid,
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        configuration_cid=base.configuration_cid,
        network_policy_cid=base.network_policy_cid,
        proof_schema_version=base.proof_schema_version,
        canonicalization_version=base.canonicalization_version,
        dependency_graph_schema_version=base.dependency_graph_schema_version,
        permitted_removals=(),
        logical_epoch=base.logical_epoch,
        selected_unit_ids=["unit/a", "unit/b", "unit/c"],
    )

    # Authorized removal of unit/b.
    removal = UnitRemovalAuthorization(
        proof_unit_id="unit/b",
        policy_cid=base.policy_cid,
        removal_reason="test_deleted",
        risk_class="medium",
        tombstone_cid=_cid("tombstone:unit/b"),
        authorized=True,
        logical_epoch=base.logical_epoch + 1,
    )
    remaining = tuple(
        unit for unit in base.required_units if unit.proof_unit_id != "unit/b"
    )
    with_authorized_removal = build_verification_requirement_manifest(
        repository_id=base.repository_id,
        revision=base.revision,
        repository_state_cid=base.repository_state_cid,
        source_root_cid=base.source_root_cid,
        required_units=remaining,
        policy=base.policy_cid,
        test_selector_cid=base.test_selector_cid,
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        configuration_cid=base.configuration_cid,
        network_policy_cid=base.network_policy_cid,
        proof_schema_version=base.proof_schema_version,
        canonicalization_version=base.canonicalization_version,
        dependency_graph_schema_version=base.dependency_graph_schema_version,
        permitted_removals=(removal,),
        logical_epoch=base.logical_epoch + 1,
    )
    assert_no_unauthorized_disappearance(
        base, with_authorized_removal, policy=policy
    )

    context_mutations: dict[str, str] = {}
    for field, value in (
        ("policy_cid", sample_verification_policy(policy_id="policy/alt").policy_cid()),
        ("test_selector_cid", _cid("selector-mutated")),
        ("environment_cid", _cid("environment-mutated")),
        ("dependency_lock_cid", _cid("lock-mutated")),
        ("configuration_cid", _cid("config-mutated")),
        ("source_root_cid", _cid("source-root-mutated")),
        ("repository_state_cid", _cid("repository-state-mutated")),
        ("network_policy_cid", _cid("network-policy-mutated")),
        ("canonicalization_version", "ips/canonicalization@2"),
        ("dependency_graph_schema_version", "graph@2"),
        ("proof_schema_version", "2"),
        ("revision", "rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
        ("logical_epoch", base.logical_epoch + 7),
    ):
        mutated_payload = base.to_canonical()
        # Rebuild via from_canonical with field override; required_units stay
        # as nested objects so from_canonical succeeds.
        mutated_payload[field] = value
        mutated = VerificationRequirementManifest.from_canonical(mutated_payload)
        mutated_root = mutated.manifest_root()
        if mutated_root == base_root:
            raise ManifestError(
                f"context mutation of {field} did not change manifest root"
            )
        context_mutations[field] = mutated_root

    required_set_root = with_added.manifest_root()
    if required_set_root == base_root:
        raise ManifestError("required-set addition did not change manifest root")

    return {
        "schema": f"{MANIFEST_NAMESPACE}/known-vectors@{SCHEMA_MAJOR}",
        "manifest_subset": MANIFEST_SUBSET,
        "verification_policy_schema": VERIFICATION_POLICY_SCHEMA,
        "manifest_schema": VERIFICATION_REQUIREMENT_MANIFEST_SCHEMA,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "base": {
            "policy": policy.to_canonical(),
            "policy_cid": policy.policy_cid(),
            "manifest": base.to_canonical(),
            "manifest_root": base_root,
        },
        "added_selected_unit": {
            "manifest": with_added.to_canonical(),
            "manifest_root": required_set_root,
            "required_unit_ids": list(with_added.required_unit_ids),
        },
        "authorized_removal": {
            "manifest": with_authorized_removal.to_canonical(),
            "manifest_root": with_authorized_removal.manifest_root(),
            "removal": removal.to_canonical(),
        },
        "context_mutations": context_mutations,
    }


__all__ = (
    "ABSENCE_TOKEN",
    "CANONICALIZATION_VERSION",
    "CLOSED_REMOVAL_REASONS",
    "MANIFEST_REQUIRED_FIELDS",
    "MANIFEST_SUBSET",
    "PROOF_SCHEMA_VERSION",
    "REQUIRED_UNIT_DESCRIPTOR_SCHEMA",
    "TYPED_ABSENCE",
    "UNIT_REMOVAL_AUTHORIZATION_SCHEMA",
    "VERIFICATION_POLICY_SCHEMA",
    "VERIFICATION_REQUIREMENT_MANIFEST_SCHEMA",
    "ManifestError",
    "RequiredUnitDescriptor",
    "UnitRemovalAuthorization",
    "VerificationPolicy",
    "VerificationRequirementManifest",
    "assert_no_unauthorized_disappearance",
    "build_verification_requirement_manifest",
    "known_vectors",
    "sample_required_unit",
    "sample_verification_policy",
    "sample_verification_requirement_manifest",
)
