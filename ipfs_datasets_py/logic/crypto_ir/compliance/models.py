"""Strict, offline sanctions evidence and policy records.

The records in this module describe authority, source snapshots, evidence, and
reviewed policy inputs.  They do not fetch sanctions data and they do not make
legal determinations.  In particular, a :class:`LegalPolicyApproval` is
separate from both list authority and screening evidence and binds the exact
digest of the rules it approves.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Final, TypeVar

from ...ir_core.canonical import canonical_json_bytes
from ..identity import crypto_ir_identity
from ..provenance import AuthorityKind
from ..schema_versions import CRYPTO_IR_KERNEL_SCHEMA_VERSION
from ..verdicts import SanctionsMatchLevel


COMPLIANCE_SCHEMA_VERSION: Final[str] = "ipfs-datasets.crypto-ir.compliance@1.0.0"
SANCTIONS_POLICY_SCHEMA_VERSION: Final[str] = (
    "ipfs-datasets.crypto-ir.sanctions-policy@1.0.0"
)
SANCTIONS_SNAPSHOT_SCHEMA_VERSION: Final[str] = (
    "ipfs-datasets.crypto-ir.sanctions-snapshot@1.0.0"
)
CRYPTO_IR_COMPLIANCE_DOMAIN: Final[str] = "crypto-ir.compliance"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_JURISDICTION_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,15}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_T = TypeVar("_T")


class ComplianceModelError(ValueError):
    """Raised when sanctions evidence or policy input is malformed."""


class OwnershipKind(str, Enum):
    """Whether evidence describes one owner or an aggregate calculation."""

    ENTITY = "entity"
    AGGREGATE = "aggregate"


class AssociationKind(str, Enum):
    """Association evidence classes that cannot become designations."""

    DIRECT = "direct_association"
    BOUNDED_INDIRECT = "bounded_indirect_exposure"
    HEURISTIC = "heuristic_association"


class SanctionsPolicyOutcome(str, Enum):
    """Screening results, distinct from transaction authorization."""

    ALLOW = "allow"
    REVIEW = "review"
    DENY = "deny"
    INCONCLUSIVE = "inconclusive"
    STALE = "stale"
    ERROR = "error"


class LicenseDisposition(str, Enum):
    """A policy-selected treatment of an applicable license."""

    IGNORE = "ignore"
    REVIEW = "review"
    APPLY_POLICY_RULE = "apply_policy_rule"


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise ComplianceModelError(f"{name} must be a string")
    if value != value.strip():
        raise ComplianceModelError(f"{name} must not have surrounding whitespace")
    if not allow_empty and not value:
        raise ComplianceModelError(f"{name} must be a non-empty string")
    return value


def _identifier(value: Any, name: str) -> str:
    result = _text(value, name)
    if not _ID_RE.fullmatch(result):
        raise ComplianceModelError(f"{name} must be a stable identifier")
    return result


def _digest(value: Any, name: str) -> str:
    result = _text(value, name)
    if not _SHA256_RE.fullmatch(result):
        raise ComplianceModelError(f"{name} must be a sha256:<64 lowercase hex> digest")
    return result


def _instant(value: Any, name: str, *, allow_empty: bool = False) -> str:
    result = _text(value, name, allow_empty=allow_empty)
    if not result:
        return result
    candidate = result[:-1] + "+00:00" if result.endswith("Z") else result
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ComplianceModelError(f"{name} must be an ISO-8601 instant") from exc
    if parsed.tzinfo is None:
        raise ComplianceModelError(f"{name} must include a timezone")
    return result


def _enum(enum_type: type[_T], value: Any, name: str) -> _T:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)  # type: ignore[call-arg]
    except (TypeError, ValueError) as exc:
        raise ComplianceModelError(f"unsupported {name}: {value!r}") from exc


def _tuple(values: Any, item_type: type[_T], name: str) -> tuple[_T, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ComplianceModelError(f"{name} must be a sequence")
    result: list[_T] = []
    for item in values:
        if isinstance(item, item_type):
            result.append(item)
        elif isinstance(item, Mapping) and hasattr(item_type, "from_dict"):
            result.append(item_type.from_dict(item))  # type: ignore[attr-defined]
        else:
            raise ComplianceModelError(
                f"{name} entries must be {item_type.__name__} records"
            )
    return tuple(result)


def _ids(values: Any, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise ComplianceModelError(f"{name} must be a sequence")
    result = tuple(_identifier(item, name) for item in values)
    if not allow_empty and not result:
        raise ComplianceModelError(f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise ComplianceModelError(f"{name} values must be unique")
    return result


def _known(value: Mapping[str, Any], fields: frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - fields)
    if unknown:
        raise ComplianceModelError(f"unknown {name} field(s): {', '.join(unknown)}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ComplianceModelError(f"{name} must be a mapping")
    return value


def _window(effective_from: str, effective_until: str) -> None:
    if effective_from and effective_until:
        start = _parse_instant(effective_from)
        end = _parse_instant(effective_until)
        if end <= start:
            raise ComplianceModelError(
                "effective_until must be later than effective_from"
            )


def _parse_instant(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(candidate)


def _identity(record: Any, kind: str):
    return crypto_ir_identity(
        record.to_dict(),
        schema_version=CRYPTO_IR_KERNEL_SCHEMA_VERSION,
        domain=f"{CRYPTO_IR_COMPLIANCE_DOMAIN}.{kind}",
    )


def _schema(value: Any, expected: str, name: str = "schema_version") -> str:
    result = _text(value, name)
    if result != expected:
        raise ComplianceModelError(f"unsupported {name}: {result}")
    return result


@dataclass(frozen=True, slots=True)
class Jurisdiction:
    """A typed jurisdiction scope; the code is policy data, not inference."""

    code: str
    name: str

    def __post_init__(self) -> None:
        code = _text(self.code, "code")
        if not _JURISDICTION_RE.fullmatch(code):
            raise ComplianceModelError("code must be an uppercase jurisdiction code")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "name", _text(self.name, "name"))

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "name": self.name}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Jurisdiction":
        value = _mapping(value, "Jurisdiction")
        _known(value, frozenset({"code", "name"}), "Jurisdiction")
        return cls(code=value.get("code", ""), name=value.get("name", ""))


@dataclass(frozen=True, slots=True)
class SanctionsProgram:
    """One exact sanctions program identity under a source authority."""

    program_id: str
    name: str
    authority_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", _identifier(self.program_id, "program_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self, "authority_id", _identifier(self.authority_id, "authority_id")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "name": self.name,
            "program_id": self.program_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SanctionsProgram":
        value = _mapping(value, "SanctionsProgram")
        _known(
            value,
            frozenset({"program_id", "name", "authority_id"}),
            "SanctionsProgram",
        )
        return cls(
            program_id=value.get("program_id", ""),
            name=value.get("name", ""),
            authority_id=value.get("authority_id", ""),
        )


@dataclass(frozen=True, slots=True)
class SanctionsAuthority:
    """The publisher of a sanctions list, not a policy approver."""

    authority_id: str
    name: str
    jurisdiction: Jurisdiction
    source_uri: str
    schema_version: str = COMPLIANCE_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "authority_id", _identifier(self.authority_id, "authority_id")
        )
        object.__setattr__(self, "name", _text(self.name, "name"))
        if not isinstance(self.jurisdiction, Jurisdiction):
            if not isinstance(self.jurisdiction, Mapping):
                raise ComplianceModelError("jurisdiction must be a Jurisdiction")
            object.__setattr__(
                self, "jurisdiction", Jurisdiction.from_dict(self.jurisdiction)
            )
        object.__setattr__(self, "source_uri", _text(self.source_uri, "source_uri"))
        object.__setattr__(
            self,
            "schema_version",
            _schema(self.schema_version, COMPLIANCE_SCHEMA_VERSION),
        )

    @property
    def identity(self):
        return _identity(self, "authority")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "jurisdiction": self.jurisdiction.to_dict(),
            "name": self.name,
            "schema_version": self.schema_version,
            "source_uri": self.source_uri,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SanctionsAuthority":
        value = _mapping(value, "SanctionsAuthority")
        _known(
            value,
            frozenset(
                {"authority_id", "name", "jurisdiction", "source_uri", "schema_version"}
            ),
            "SanctionsAuthority",
        )
        return cls(
            authority_id=value.get("authority_id", ""),
            name=value.get("name", ""),
            jurisdiction=Jurisdiction.from_dict(value.get("jurisdiction", {})),
            source_uri=value.get("source_uri", ""),
            schema_version=value.get("schema_version", COMPLIANCE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SanctionsList:
    """A typed list identity maintained by one sanctions authority."""

    list_id: str
    name: str
    authority_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "list_id", _identifier(self.list_id, "list_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(
            self, "authority_id", _identifier(self.authority_id, "authority_id")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "list_id": self.list_id,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SanctionsList":
        value = _mapping(value, "SanctionsList")
        _known(
            value,
            frozenset({"list_id", "name", "authority_id"}),
            "SanctionsList",
        )
        return cls(
            list_id=value.get("list_id", ""),
            name=value.get("name", ""),
            authority_id=value.get("authority_id", ""),
        )


@dataclass(frozen=True, slots=True)
class DigitalCurrencyIdentifier:
    """One exact, chain-qualified identifier stated by a designation."""

    identifier_id: str
    chain_namespace: str
    network: str
    address: str
    asset_reference: str = ""

    def __post_init__(self) -> None:
        for name in ("identifier_id", "chain_namespace", "network"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "address", _text(self.address, "address"))
        object.__setattr__(
            self,
            "asset_reference",
            _text(self.asset_reference, "asset_reference", allow_empty=True),
        )

    @property
    def comparison_key(self) -> tuple[str, str, str, str]:
        return (
            self.chain_namespace,
            self.network,
            self.address,
            self.asset_reference,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "asset_reference": self.asset_reference,
            "chain_namespace": self.chain_namespace,
            "identifier_id": self.identifier_id,
            "network": self.network,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DigitalCurrencyIdentifier":
        value = _mapping(value, "DigitalCurrencyIdentifier")
        _known(
            value,
            frozenset(
                {
                    "identifier_id",
                    "chain_namespace",
                    "network",
                    "address",
                    "asset_reference",
                }
            ),
            "DigitalCurrencyIdentifier",
        )
        return cls(
            identifier_id=value.get("identifier_id", ""),
            chain_namespace=value.get("chain_namespace", ""),
            network=value.get("network", ""),
            address=value.get("address", ""),
            asset_reference=value.get("asset_reference", ""),
        )


@dataclass(frozen=True, slots=True)
class DesignationRecord:
    """A time-scoped named-party designation from one snapshot."""

    designation_id: str
    party_id: str
    primary_name: str
    authority_id: str
    program_ids: tuple[str, ...]
    jurisdiction_codes: tuple[str, ...]
    identifiers: tuple[DigitalCurrencyIdentifier, ...] = ()
    aliases: tuple[str, ...] = ()
    effective_from: str = ""
    effective_until: str = ""

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        for name in ("designation_id", "party_id", "authority_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "primary_name", _text(self.primary_name, "primary_name"))
        object.__setattr__(
            self, "program_ids", _ids(self.program_ids, "program_ids", allow_empty=False)
        )
        jurisdiction_codes = tuple(
            _text(item, "jurisdiction_codes") for item in self.jurisdiction_codes
        )
        if not jurisdiction_codes or len(jurisdiction_codes) != len(
            set(jurisdiction_codes)
        ):
            raise ComplianceModelError(
                "jurisdiction_codes must be a non-empty unique sequence"
            )
        if any(not _JURISDICTION_RE.fullmatch(item) for item in jurisdiction_codes):
            raise ComplianceModelError("jurisdiction_codes contains an invalid code")
        object.__setattr__(self, "jurisdiction_codes", jurisdiction_codes)
        object.__setattr__(
            self,
            "identifiers",
            _tuple(self.identifiers, DigitalCurrencyIdentifier, "identifiers"),
        )
        if len({item.identifier_id for item in self.identifiers}) != len(
            self.identifiers
        ):
            raise ComplianceModelError("identifier ids must be unique")
        aliases = tuple(_text(item, "aliases") for item in self.aliases)
        if len(aliases) != len(set(aliases)):
            raise ComplianceModelError("aliases must be unique")
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(
            self,
            "effective_from",
            _instant(self.effective_from, "effective_from", allow_empty=True),
        )
        object.__setattr__(
            self,
            "effective_until",
            _instant(self.effective_until, "effective_until", allow_empty=True),
        )
        _window(self.effective_from, self.effective_until)

    def is_effective_at(self, instant: str) -> bool:
        at = _parse_instant(_instant(instant, "instant"))
        if self.effective_from and at < _parse_instant(self.effective_from):
            return False
        if self.effective_until and at >= _parse_instant(self.effective_until):
            return False
        return True

    @property
    def identity(self):
        return _identity(self, "designation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "authority_id": self.authority_id,
            "designation_id": self.designation_id,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "identifiers": [item.to_dict() for item in self.identifiers],
            "jurisdiction_codes": list(self.jurisdiction_codes),
            "party_id": self.party_id,
            "primary_name": self.primary_name,
            "program_ids": list(self.program_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DesignationRecord":
        value = _mapping(value, "DesignationRecord")
        fields = frozenset(
            {
                "designation_id",
                "party_id",
                "primary_name",
                "authority_id",
                "program_ids",
                "jurisdiction_codes",
                "identifiers",
                "aliases",
                "effective_from",
                "effective_until",
            }
        )
        _known(value, fields, "DesignationRecord")
        return cls(
            designation_id=value.get("designation_id", ""),
            party_id=value.get("party_id", ""),
            primary_name=value.get("primary_name", ""),
            authority_id=value.get("authority_id", ""),
            program_ids=tuple(value.get("program_ids", ())),
            jurisdiction_codes=tuple(value.get("jurisdiction_codes", ())),
            identifiers=_tuple(
                value.get("identifiers", ()),
                DigitalCurrencyIdentifier,
                "identifiers",
            ),
            aliases=tuple(value.get("aliases", ())),
            effective_from=value.get("effective_from", ""),
            effective_until=value.get("effective_until", ""),
        )


@dataclass(frozen=True, slots=True)
class SanctionsSnapshot:
    """Immutable revision of one exact sanctions list."""

    snapshot_id: str
    authority: SanctionsAuthority
    sanctions_list: SanctionsList
    programs: tuple[SanctionsProgram, ...]
    jurisdictions: tuple[Jurisdiction, ...]
    revision: str
    published_at: str
    effective_at: str
    retrieved_at: str
    content_digest: str
    designations: tuple[DesignationRecord, ...]
    complete: bool
    supersedes_snapshot_id: str = ""
    schema_version: str = SANCTIONS_SNAPSHOT_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _identifier(self.snapshot_id, "snapshot_id"))
        if not isinstance(self.authority, SanctionsAuthority):
            object.__setattr__(
                self,
                "authority",
                SanctionsAuthority.from_dict(_mapping(self.authority, "authority")),
            )
        if not isinstance(self.sanctions_list, SanctionsList):
            object.__setattr__(
                self,
                "sanctions_list",
                SanctionsList.from_dict(_mapping(self.sanctions_list, "sanctions_list")),
            )
        if self.sanctions_list.authority_id != self.authority.authority_id:
            raise ComplianceModelError("sanctions_list authority does not match authority")
        object.__setattr__(
            self, "programs", _tuple(self.programs, SanctionsProgram, "programs")
        )
        if not self.programs:
            raise ComplianceModelError("programs must not be empty")
        program_ids = [item.program_id for item in self.programs]
        if len(program_ids) != len(set(program_ids)):
            raise ComplianceModelError("program ids must be unique")
        if any(
            item.authority_id != self.authority.authority_id for item in self.programs
        ):
            raise ComplianceModelError("program authority does not match snapshot")
        object.__setattr__(
            self,
            "jurisdictions",
            _tuple(self.jurisdictions, Jurisdiction, "jurisdictions"),
        )
        jurisdiction_codes = [item.code for item in self.jurisdictions]
        if not jurisdiction_codes or len(jurisdiction_codes) != len(
            set(jurisdiction_codes)
        ):
            raise ComplianceModelError("jurisdictions must be non-empty and unique")
        if self.authority.jurisdiction.code not in jurisdiction_codes:
            raise ComplianceModelError(
                "snapshot jurisdictions must include the authority jurisdiction"
            )
        object.__setattr__(self, "revision", _identifier(self.revision, "revision"))
        for name in ("published_at", "effective_at", "retrieved_at"):
            object.__setattr__(self, name, _instant(getattr(self, name), name))
        if _parse_instant(self.retrieved_at) < _parse_instant(self.published_at):
            raise ComplianceModelError("retrieved_at must not precede published_at")
        object.__setattr__(
            self, "content_digest", _digest(self.content_digest, "content_digest")
        )
        object.__setattr__(
            self,
            "designations",
            _tuple(self.designations, DesignationRecord, "designations"),
        )
        designation_ids = [item.designation_id for item in self.designations]
        if len(designation_ids) != len(set(designation_ids)):
            raise ComplianceModelError("designation ids must be unique")
        if any(
            item.authority_id != self.authority.authority_id
            for item in self.designations
        ):
            raise ComplianceModelError("designation authority does not match snapshot")
        if any(
            not set(item.program_ids).issubset(program_ids)
            for item in self.designations
        ):
            raise ComplianceModelError("designation references an unknown program")
        if any(
            not set(item.jurisdiction_codes).issubset(jurisdiction_codes)
            for item in self.designations
        ):
            raise ComplianceModelError("designation references an unknown jurisdiction")
        if type(self.complete) is not bool:
            raise ComplianceModelError("complete must be a boolean")
        object.__setattr__(
            self,
            "supersedes_snapshot_id",
            (
                _identifier(self.supersedes_snapshot_id, "supersedes_snapshot_id")
                if self.supersedes_snapshot_id
                else ""
            ),
        )
        object.__setattr__(
            self,
            "schema_version",
            _schema(self.schema_version, SANCTIONS_SNAPSHOT_SCHEMA_VERSION),
        )

    @property
    def identity(self):
        return _identity(self, "snapshot")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.to_dict(),
            "complete": self.complete,
            "content_digest": self.content_digest,
            "designations": [item.to_dict() for item in self.designations],
            "effective_at": self.effective_at,
            "published_at": self.published_at,
            "programs": [item.to_dict() for item in self.programs],
            "retrieved_at": self.retrieved_at,
            "revision": self.revision,
            "sanctions_list": self.sanctions_list.to_dict(),
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "supersedes_snapshot_id": self.supersedes_snapshot_id,
            "jurisdictions": [item.to_dict() for item in self.jurisdictions],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SanctionsSnapshot":
        value = _mapping(value, "SanctionsSnapshot")
        fields = frozenset(
            {
                "snapshot_id",
                "authority",
                "sanctions_list",
                "programs",
                "jurisdictions",
                "revision",
                "published_at",
                "effective_at",
                "retrieved_at",
                "content_digest",
                "designations",
                "complete",
                "supersedes_snapshot_id",
                "schema_version",
            }
        )
        _known(value, fields, "SanctionsSnapshot")
        return cls(
            snapshot_id=value.get("snapshot_id", ""),
            authority=SanctionsAuthority.from_dict(value.get("authority", {})),
            sanctions_list=SanctionsList.from_dict(value.get("sanctions_list", {})),
            programs=_tuple(
                value.get("programs", ()), SanctionsProgram, "programs"
            ),
            jurisdictions=_tuple(
                value.get("jurisdictions", ()), Jurisdiction, "jurisdictions"
            ),
            revision=value.get("revision", ""),
            published_at=value.get("published_at", ""),
            effective_at=value.get("effective_at", ""),
            retrieved_at=value.get("retrieved_at", ""),
            content_digest=value.get("content_digest", ""),
            designations=_tuple(
                value.get("designations", ()), DesignationRecord, "designations"
            ),
            complete=value.get("complete"),
            supersedes_snapshot_id=value.get("supersedes_snapshot_id", ""),
            schema_version=value.get(
                "schema_version", SANCTIONS_SNAPSHOT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class OwnershipInterest:
    """One ownership component measured in integer basis points."""

    owner_party_id: str
    ownership_basis_points: int
    designation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "owner_party_id", _identifier(self.owner_party_id, "owner_party_id")
        )
        if type(self.ownership_basis_points) is not int:
            raise ComplianceModelError("ownership_basis_points must be an integer")
        if not 0 <= self.ownership_basis_points <= 10_000:
            raise ComplianceModelError("ownership_basis_points must be in 0..10000")
        object.__setattr__(
            self,
            "designation_ids",
            _ids(self.designation_ids, "designation_ids", allow_empty=False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "designation_ids": list(self.designation_ids),
            "owner_party_id": self.owner_party_id,
            "ownership_basis_points": self.ownership_basis_points,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OwnershipInterest":
        value = _mapping(value, "OwnershipInterest")
        _known(
            value,
            frozenset(
                {"owner_party_id", "ownership_basis_points", "designation_ids"}
            ),
            "OwnershipInterest",
        )
        return cls(
            owner_party_id=value.get("owner_party_id", ""),
            ownership_basis_points=value.get("ownership_basis_points"),
            designation_ids=tuple(value.get("designation_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class OwnershipEvidence:
    """Evidence for direct-entity or aggregate blocked ownership."""

    evidence_id: str
    subject_party_id: str
    kind: OwnershipKind
    interests: tuple[OwnershipInterest, ...]
    source_digests: tuple[str, ...]
    observed_at: str
    effective_from: str
    effective_until: str = ""
    complete: bool = False

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _identifier(self.evidence_id, "evidence_id"))
        object.__setattr__(
            self,
            "subject_party_id",
            _identifier(self.subject_party_id, "subject_party_id"),
        )
        object.__setattr__(self, "kind", _enum(OwnershipKind, self.kind, "kind"))
        object.__setattr__(
            self,
            "interests",
            _tuple(self.interests, OwnershipInterest, "interests"),
        )
        if not self.interests:
            raise ComplianceModelError("interests must not be empty")
        owners = [item.owner_party_id for item in self.interests]
        if len(owners) != len(set(owners)):
            raise ComplianceModelError("ownership interests must have unique owners")
        if self.kind is OwnershipKind.ENTITY and len(self.interests) != 1:
            raise ComplianceModelError("entity ownership evidence requires one owner")
        if sum(item.ownership_basis_points for item in self.interests) > 10_000:
            raise ComplianceModelError(
                "aggregate ownership basis points must not exceed 10000"
            )
        digests = tuple(_digest(item, "source_digests") for item in self.source_digests)
        if not digests or len(digests) != len(set(digests)):
            raise ComplianceModelError("source_digests must be non-empty and unique")
        object.__setattr__(self, "source_digests", digests)
        object.__setattr__(self, "observed_at", _instant(self.observed_at, "observed_at"))
        object.__setattr__(
            self, "effective_from", _instant(self.effective_from, "effective_from")
        )
        object.__setattr__(
            self,
            "effective_until",
            _instant(self.effective_until, "effective_until", allow_empty=True),
        )
        _window(self.effective_from, self.effective_until)
        if type(self.complete) is not bool:
            raise ComplianceModelError("complete must be a boolean")

    @property
    def aggregate_basis_points(self) -> int:
        return sum(item.ownership_basis_points for item in self.interests)

    def is_effective_at(self, instant: str) -> bool:
        at = _parse_instant(_instant(instant, "instant"))
        if at < _parse_instant(self.effective_from):
            return False
        return not self.effective_until or at < _parse_instant(self.effective_until)

    @property
    def identity(self):
        return _identity(self, "ownership-evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "evidence_id": self.evidence_id,
            "interests": [item.to_dict() for item in self.interests],
            "kind": self.kind.value,
            "observed_at": self.observed_at,
            "source_digests": list(self.source_digests),
            "subject_party_id": self.subject_party_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OwnershipEvidence":
        value = _mapping(value, "OwnershipEvidence")
        fields = frozenset(
            {
                "evidence_id",
                "subject_party_id",
                "kind",
                "interests",
                "source_digests",
                "observed_at",
                "effective_from",
                "effective_until",
                "complete",
            }
        )
        _known(value, fields, "OwnershipEvidence")
        return cls(
            evidence_id=value.get("evidence_id", ""),
            subject_party_id=value.get("subject_party_id", ""),
            kind=value.get("kind", ""),
            interests=_tuple(
                value.get("interests", ()), OwnershipInterest, "interests"
            ),
            source_digests=tuple(value.get("source_digests", ())),
            observed_at=value.get("observed_at", ""),
            effective_from=value.get("effective_from", ""),
            effective_until=value.get("effective_until", ""),
            complete=value.get("complete", False),
        )


@dataclass(frozen=True, slots=True)
class LicenseRecord:
    """A scoped license/exception artifact; never an unbounded exemption."""

    license_id: str
    authority_id: str
    license_type: str
    subject_party_ids: tuple[str, ...]
    program_ids: tuple[str, ...]
    jurisdiction_codes: tuple[str, ...]
    activity_ids: tuple[str, ...]
    effective_from: str
    effective_until: str
    approval_artifact_digest: str

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        for name in ("license_id", "authority_id", "license_type"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in ("subject_party_ids", "program_ids", "activity_ids"):
            object.__setattr__(
                self, name, _ids(getattr(self, name), name, allow_empty=False)
            )
        jurisdictions = tuple(
            _text(item, "jurisdiction_codes") for item in self.jurisdiction_codes
        )
        if not jurisdictions or any(
            not _JURISDICTION_RE.fullmatch(item) for item in jurisdictions
        ):
            raise ComplianceModelError("jurisdiction_codes must be non-empty and valid")
        if len(jurisdictions) != len(set(jurisdictions)):
            raise ComplianceModelError("jurisdiction_codes must be unique")
        object.__setattr__(self, "jurisdiction_codes", jurisdictions)
        object.__setattr__(
            self, "effective_from", _instant(self.effective_from, "effective_from")
        )
        object.__setattr__(
            self, "effective_until", _instant(self.effective_until, "effective_until")
        )
        _window(self.effective_from, self.effective_until)
        object.__setattr__(
            self,
            "approval_artifact_digest",
            _digest(self.approval_artifact_digest, "approval_artifact_digest"),
        )

    def is_applicable(
        self,
        *,
        subject_party_id: str,
        program_ids: Sequence[str],
        jurisdiction_code: str,
        activity_id: str,
        at_time: str,
    ) -> bool:
        at = _parse_instant(_instant(at_time, "at_time"))
        return (
            subject_party_id in self.subject_party_ids
            and bool(set(program_ids) & set(self.program_ids))
            and jurisdiction_code in self.jurisdiction_codes
            and activity_id in self.activity_ids
            and _parse_instant(self.effective_from)
            <= at
            < _parse_instant(self.effective_until)
        )

    @property
    def identity(self):
        return _identity(self, "license")

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_ids": list(self.activity_ids),
            "approval_artifact_digest": self.approval_artifact_digest,
            "authority_id": self.authority_id,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "jurisdiction_codes": list(self.jurisdiction_codes),
            "license_id": self.license_id,
            "license_type": self.license_type,
            "program_ids": list(self.program_ids),
            "subject_party_ids": list(self.subject_party_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LicenseRecord":
        value = _mapping(value, "LicenseRecord")
        fields = frozenset(
            {
                "license_id",
                "authority_id",
                "license_type",
                "subject_party_ids",
                "program_ids",
                "jurisdiction_codes",
                "activity_ids",
                "effective_from",
                "effective_until",
                "approval_artifact_digest",
            }
        )
        _known(value, fields, "LicenseRecord")
        return cls(
            license_id=value.get("license_id", ""),
            authority_id=value.get("authority_id", ""),
            license_type=value.get("license_type", ""),
            subject_party_ids=tuple(value.get("subject_party_ids", ())),
            program_ids=tuple(value.get("program_ids", ())),
            jurisdiction_codes=tuple(value.get("jurisdiction_codes", ())),
            activity_ids=tuple(value.get("activity_ids", ())),
            effective_from=value.get("effective_from", ""),
            effective_until=value.get("effective_until", ""),
            approval_artifact_digest=value.get("approval_artifact_digest", ""),
        )


@dataclass(frozen=True, slots=True)
class AssociationEvidence:
    """Direct, bounded-indirect, or heuristic evidence without designation power."""

    evidence_id: str
    kind: AssociationKind
    subject_party_id: str
    target_party_id: str
    source_digests: tuple[str, ...]
    observed_at: str
    complete: bool
    path_depth: int = 0
    exposure_basis_points: int | None = None

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _identifier(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "kind", _enum(AssociationKind, self.kind, "kind"))
        for name in ("subject_party_id", "target_party_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        digests = tuple(_digest(item, "source_digests") for item in self.source_digests)
        if not digests or len(digests) != len(set(digests)):
            raise ComplianceModelError("source_digests must be non-empty and unique")
        object.__setattr__(self, "source_digests", digests)
        object.__setattr__(self, "observed_at", _instant(self.observed_at, "observed_at"))
        if type(self.complete) is not bool:
            raise ComplianceModelError("complete must be a boolean")
        if type(self.path_depth) is not int or self.path_depth < 0:
            raise ComplianceModelError("path_depth must be a non-negative integer")
        if self.kind is AssociationKind.DIRECT and self.path_depth not in (0, 1):
            raise ComplianceModelError("direct association path_depth must be 0 or 1")
        if self.kind is AssociationKind.BOUNDED_INDIRECT and self.path_depth < 2:
            raise ComplianceModelError("bounded indirect exposure needs path_depth >= 2")
        if self.exposure_basis_points is not None and (
            type(self.exposure_basis_points) is not int
            or not 0 <= self.exposure_basis_points <= 10_000
        ):
            raise ComplianceModelError("exposure_basis_points must be in 0..10000")

    @property
    def match_level(self) -> SanctionsMatchLevel:
        return {
            AssociationKind.DIRECT: SanctionsMatchLevel.DIRECT_ASSOCIATION,
            AssociationKind.BOUNDED_INDIRECT: (
                SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE
            ),
            AssociationKind.HEURISTIC: SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
        }[self.kind]

    @property
    def identity(self):
        return _identity(self, "association-evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "evidence_id": self.evidence_id,
            "exposure_basis_points": self.exposure_basis_points,
            "kind": self.kind.value,
            "observed_at": self.observed_at,
            "path_depth": self.path_depth,
            "source_digests": list(self.source_digests),
            "subject_party_id": self.subject_party_id,
            "target_party_id": self.target_party_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssociationEvidence":
        value = _mapping(value, "AssociationEvidence")
        fields = frozenset(
            {
                "evidence_id",
                "kind",
                "subject_party_id",
                "target_party_id",
                "source_digests",
                "observed_at",
                "complete",
                "path_depth",
                "exposure_basis_points",
            }
        )
        _known(value, fields, "AssociationEvidence")
        return cls(
            evidence_id=value.get("evidence_id", ""),
            kind=value.get("kind", ""),
            subject_party_id=value.get("subject_party_id", ""),
            target_party_id=value.get("target_party_id", ""),
            source_digests=tuple(value.get("source_digests", ())),
            observed_at=value.get("observed_at", ""),
            complete=value.get("complete", False),
            path_depth=value.get("path_depth", 0),
            exposure_basis_points=value.get("exposure_basis_points"),
        )


@dataclass(frozen=True, slots=True)
class SanctionsMatch:
    """One typed match that must cite evidence appropriate to its level."""

    match_id: str
    level: SanctionsMatchLevel
    subject_party_id: str
    snapshot_id: str
    designation_ids: tuple[str, ...] = ()
    identifier_id: str = ""
    ownership_evidence_id: str = ""
    association_evidence_id: str = ""

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.RESULT

    def __post_init__(self) -> None:
        for name in ("match_id", "subject_party_id", "snapshot_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        level = _enum(SanctionsMatchLevel, self.level, "level")
        if level in {
            SanctionsMatchLevel.NO_MATCH,
            SanctionsMatchLevel.UNKNOWN,
            SanctionsMatchLevel.ERROR,
        }:
            raise ComplianceModelError("SanctionsMatch must represent positive evidence")
        object.__setattr__(self, "level", level)
        object.__setattr__(
            self, "designation_ids", _ids(self.designation_ids, "designation_ids")
        )
        for name in (
            "identifier_id",
            "ownership_evidence_id",
            "association_evidence_id",
        ):
            value = getattr(self, name)
            object.__setattr__(
                self, name, _identifier(value, name) if value else ""
            )
        if level is SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER:
            if not self.identifier_id or not self.designation_ids:
                raise ComplianceModelError(
                    "exact listed identifier needs identifier_id and designation_ids"
                )
            if self.ownership_evidence_id or self.association_evidence_id:
                raise ComplianceModelError(
                    "exact listed identifier cannot cite ownership or association"
                )
        elif level is SanctionsMatchLevel.NAMED_DESIGNATED_PARTY:
            if not self.designation_ids:
                raise ComplianceModelError("named party needs designation_ids")
            if (
                self.identifier_id
                or self.ownership_evidence_id
                or self.association_evidence_id
            ):
                raise ComplianceModelError(
                    "named party cannot cite identifier, ownership, or association"
                )
        elif level is SanctionsMatchLevel.OWNED_ENTITY:
            if not self.ownership_evidence_id or not self.designation_ids:
                raise ComplianceModelError(
                    "owned entity needs ownership evidence and designation ids"
                )
            if self.identifier_id or self.association_evidence_id:
                raise ComplianceModelError(
                    "owned entity cannot cite identifier or association evidence"
                )
        else:
            if not self.association_evidence_id:
                raise ComplianceModelError(
                    "association match needs association_evidence_id"
                )
            if self.identifier_id or self.ownership_evidence_id:
                raise ComplianceModelError(
                    "association cannot cite identifier or ownership evidence"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "association_evidence_id": self.association_evidence_id,
            "designation_ids": list(self.designation_ids),
            "identifier_id": self.identifier_id,
            "level": self.level.value,
            "match_id": self.match_id,
            "ownership_evidence_id": self.ownership_evidence_id,
            "snapshot_id": self.snapshot_id,
            "subject_party_id": self.subject_party_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SanctionsMatch":
        value = _mapping(value, "SanctionsMatch")
        fields = frozenset(
            {
                "match_id",
                "level",
                "subject_party_id",
                "snapshot_id",
                "designation_ids",
                "identifier_id",
                "ownership_evidence_id",
                "association_evidence_id",
            }
        )
        _known(value, fields, "SanctionsMatch")
        return cls(
            match_id=value.get("match_id", ""),
            level=value.get("level", ""),
            subject_party_id=value.get("subject_party_id", ""),
            snapshot_id=value.get("snapshot_id", ""),
            designation_ids=tuple(value.get("designation_ids", ())),
            identifier_id=value.get("identifier_id", ""),
            ownership_evidence_id=value.get("ownership_evidence_id", ""),
            association_evidence_id=value.get("association_evidence_id", ""),
        )


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """A versioned mapping from one evidence level to one screening outcome."""

    level: SanctionsMatchLevel
    outcome: SanctionsPolicyOutcome
    reason_code: str

    def __post_init__(self) -> None:
        level = _enum(SanctionsMatchLevel, self.level, "level")
        if level in {SanctionsMatchLevel.UNKNOWN, SanctionsMatchLevel.ERROR}:
            raise ComplianceModelError("UNKNOWN and ERROR are engine states, not rules")
        object.__setattr__(self, "level", level)
        object.__setattr__(
            self, "outcome", _enum(SanctionsPolicyOutcome, self.outcome, "outcome")
        )
        object.__setattr__(
            self, "reason_code", _identifier(self.reason_code, "reason_code")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyRule":
        value = _mapping(value, "PolicyRule")
        _known(value, frozenset({"level", "outcome", "reason_code"}), "PolicyRule")
        return cls(
            level=value.get("level", ""),
            outcome=value.get("outcome", ""),
            reason_code=value.get("reason_code", ""),
        )


_REQUIRED_RULE_LEVELS: Final[frozenset[SanctionsMatchLevel]] = frozenset(
    {
        SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
        SanctionsMatchLevel.NAMED_DESIGNATED_PARTY,
        SanctionsMatchLevel.OWNED_ENTITY,
        SanctionsMatchLevel.DIRECT_ASSOCIATION,
        SanctionsMatchLevel.BOUNDED_INDIRECT_EXPOSURE,
        SanctionsMatchLevel.HEURISTIC_ASSOCIATION,
        SanctionsMatchLevel.NO_MATCH,
    }
)


@dataclass(frozen=True, slots=True)
class LegalPolicyApproval:
    """Legal-owner approval of one exact policy id, revision, and rules digest."""

    approval_id: str
    legal_owner_id: str
    policy_id: str
    policy_revision: str
    rules_digest: str
    approved_at: str
    effective_from: str
    effective_until: str
    approval_artifact_digest: str
    production_enforcement: bool

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.AUTHORIZATION

    def __post_init__(self) -> None:
        for name in (
            "approval_id",
            "legal_owner_id",
            "policy_id",
            "policy_revision",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "rules_digest", _digest(self.rules_digest, "rules_digest"))
        object.__setattr__(self, "approved_at", _instant(self.approved_at, "approved_at"))
        object.__setattr__(
            self, "effective_from", _instant(self.effective_from, "effective_from")
        )
        object.__setattr__(
            self, "effective_until", _instant(self.effective_until, "effective_until")
        )
        _window(self.effective_from, self.effective_until)
        object.__setattr__(
            self,
            "approval_artifact_digest",
            _digest(self.approval_artifact_digest, "approval_artifact_digest"),
        )
        if type(self.production_enforcement) is not bool:
            raise ComplianceModelError("production_enforcement must be a boolean")

    def is_effective_at(self, instant: str) -> bool:
        at = _parse_instant(_instant(instant, "instant"))
        return (
            _parse_instant(self.effective_from)
            <= at
            < _parse_instant(self.effective_until)
        )

    def can_authorize_transaction(self) -> bool:
        """This approval authorizes policy use, never a transaction."""

        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_artifact_digest": self.approval_artifact_digest,
            "approval_id": self.approval_id,
            "approved_at": self.approved_at,
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "legal_owner_id": self.legal_owner_id,
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "production_enforcement": self.production_enforcement,
            "rules_digest": self.rules_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegalPolicyApproval":
        value = _mapping(value, "LegalPolicyApproval")
        fields = frozenset(
            {
                "approval_id",
                "legal_owner_id",
                "policy_id",
                "policy_revision",
                "rules_digest",
                "approved_at",
                "effective_from",
                "effective_until",
                "approval_artifact_digest",
                "production_enforcement",
            }
        )
        _known(value, fields, "LegalPolicyApproval")
        return cls(
            approval_id=value.get("approval_id", ""),
            legal_owner_id=value.get("legal_owner_id", ""),
            policy_id=value.get("policy_id", ""),
            policy_revision=value.get("policy_revision", ""),
            rules_digest=value.get("rules_digest", ""),
            approved_at=value.get("approved_at", ""),
            effective_from=value.get("effective_from", ""),
            effective_until=value.get("effective_until", ""),
            approval_artifact_digest=value.get("approval_artifact_digest", ""),
            production_enforcement=value.get("production_enforcement"),
        )


@dataclass(frozen=True, slots=True)
class SanctionsPolicy:
    """Named, versioned policy inputs; no outcome or threshold is implicit."""

    policy_id: str
    revision: str
    jurisdiction_code: str
    authority_ids: tuple[str, ...]
    list_ids: tuple[str, ...]
    program_ids: tuple[str, ...]
    rules: tuple[PolicyRule, ...]
    ownership_threshold_basis_points: int
    maximum_snapshot_age_seconds: int
    license_disposition: LicenseDisposition
    license_outcome: SanctionsPolicyOutcome
    outcome_precedence: tuple[SanctionsPolicyOutcome, ...]
    effective_from: str
    effective_until: str
    approval: LegalPolicyApproval | None = None
    schema_version: str = SANCTIONS_POLICY_SCHEMA_VERSION

    LAYER: ClassVar[AuthorityKind] = AuthorityKind.DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(self, "revision", _identifier(self.revision, "revision"))
        jurisdiction = _text(self.jurisdiction_code, "jurisdiction_code")
        if not _JURISDICTION_RE.fullmatch(jurisdiction):
            raise ComplianceModelError("jurisdiction_code is invalid")
        object.__setattr__(self, "jurisdiction_code", jurisdiction)
        for name in ("authority_ids", "list_ids", "program_ids"):
            object.__setattr__(
                self, name, _ids(getattr(self, name), name, allow_empty=False)
            )
        object.__setattr__(self, "rules", _tuple(self.rules, PolicyRule, "rules"))
        levels = [rule.level for rule in self.rules]
        if len(levels) != len(set(levels)):
            raise ComplianceModelError("policy rule levels must be unique")
        if set(levels) != _REQUIRED_RULE_LEVELS:
            missing = sorted(level.value for level in _REQUIRED_RULE_LEVELS - set(levels))
            extra = sorted(level.value for level in set(levels) - _REQUIRED_RULE_LEVELS)
            raise ComplianceModelError(
                f"policy rules must cover every evidence level "
                f"(missing={missing}, extra={extra})"
            )
        if (
            type(self.ownership_threshold_basis_points) is not int
            or not 1 <= self.ownership_threshold_basis_points <= 10_000
        ):
            raise ComplianceModelError(
                "ownership_threshold_basis_points must be in 1..10000"
            )
        if (
            type(self.maximum_snapshot_age_seconds) is not int
            or self.maximum_snapshot_age_seconds < 0
        ):
            raise ComplianceModelError(
                "maximum_snapshot_age_seconds must be a non-negative integer"
            )
        object.__setattr__(
            self,
            "license_disposition",
            _enum(LicenseDisposition, self.license_disposition, "license_disposition"),
        )
        object.__setattr__(
            self,
            "license_outcome",
            _enum(SanctionsPolicyOutcome, self.license_outcome, "license_outcome"),
        )
        precedence = tuple(
            _enum(SanctionsPolicyOutcome, item, "outcome_precedence")
            for item in self.outcome_precedence
        )
        if len(precedence) != len(set(precedence)) or set(precedence) != set(
            SanctionsPolicyOutcome
        ):
            raise ComplianceModelError(
                "outcome_precedence must order every screening outcome exactly once"
            )
        object.__setattr__(self, "outcome_precedence", precedence)
        object.__setattr__(
            self, "effective_from", _instant(self.effective_from, "effective_from")
        )
        object.__setattr__(
            self, "effective_until", _instant(self.effective_until, "effective_until")
        )
        _window(self.effective_from, self.effective_until)
        if self.approval is not None and not isinstance(
            self.approval, LegalPolicyApproval
        ):
            object.__setattr__(
                self,
                "approval",
                LegalPolicyApproval.from_dict(_mapping(self.approval, "approval")),
            )
        object.__setattr__(
            self,
            "schema_version",
            _schema(self.schema_version, SANCTIONS_POLICY_SCHEMA_VERSION),
        )
        if self.approval is not None:
            if (
                self.approval.policy_id != self.policy_id
                or self.approval.policy_revision != self.revision
            ):
                raise ComplianceModelError(
                    "legal approval does not bind this policy id and revision"
                )
            if self.approval.rules_digest != self.rules_digest:
                raise ComplianceModelError(
                    "legal approval does not bind this exact policy rules digest"
                )

    def rule_for(self, level: SanctionsMatchLevel | str) -> PolicyRule:
        wanted = _enum(SanctionsMatchLevel, level, "level")
        for rule in self.rules:
            if rule.level is wanted:
                return rule
        raise ComplianceModelError(f"policy has no rule for {wanted.value}")

    def is_effective_at(self, instant: str) -> bool:
        at = _parse_instant(_instant(instant, "instant"))
        return (
            _parse_instant(self.effective_from)
            <= at
            < _parse_instant(self.effective_until)
        )

    def approved_for_production_at(self, instant: str) -> bool:
        return bool(
            self.approval
            and self.approval.production_enforcement
            and self.approval.is_effective_at(instant)
            and self.is_effective_at(instant)
        )

    def rules_payload(self) -> dict[str, Any]:
        """Return only legal-owner-reviewed inputs, excluding approval metadata."""

        return {
            "authority_ids": list(self.authority_ids),
            "effective_from": self.effective_from,
            "effective_until": self.effective_until,
            "jurisdiction_code": self.jurisdiction_code,
            "license_disposition": self.license_disposition.value,
            "license_outcome": self.license_outcome.value,
            "list_ids": list(self.list_ids),
            "maximum_snapshot_age_seconds": self.maximum_snapshot_age_seconds,
            "ownership_threshold_basis_points": (
                self.ownership_threshold_basis_points
            ),
            "outcome_precedence": [item.value for item in self.outcome_precedence],
            "policy_id": self.policy_id,
            "program_ids": list(self.program_ids),
            "revision": self.revision,
            "rules": [item.to_dict() for item in self.rules],
            "schema_version": self.schema_version,
        }

    @property
    def rules_digest(self) -> str:
        payload = canonical_json_bytes(self.rules_payload())
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"

    @property
    def identity(self):
        return _identity(self, "policy")

    def to_dict(self) -> dict[str, Any]:
        result = self.rules_payload()
        result["approval"] = self.approval.to_dict() if self.approval else None
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SanctionsPolicy":
        value = _mapping(value, "SanctionsPolicy")
        fields = frozenset(
            {
                "policy_id",
                "revision",
                "jurisdiction_code",
                "authority_ids",
                "list_ids",
                "program_ids",
                "rules",
                "ownership_threshold_basis_points",
                "maximum_snapshot_age_seconds",
                "license_disposition",
                "license_outcome",
                "outcome_precedence",
                "effective_from",
                "effective_until",
                "approval",
                "schema_version",
            }
        )
        _known(value, fields, "SanctionsPolicy")
        approval_value = value.get("approval")
        return cls(
            policy_id=value.get("policy_id", ""),
            revision=value.get("revision", ""),
            jurisdiction_code=value.get("jurisdiction_code", ""),
            authority_ids=tuple(value.get("authority_ids", ())),
            list_ids=tuple(value.get("list_ids", ())),
            program_ids=tuple(value.get("program_ids", ())),
            rules=_tuple(value.get("rules", ()), PolicyRule, "rules"),
            ownership_threshold_basis_points=value.get(
                "ownership_threshold_basis_points"
            ),
            maximum_snapshot_age_seconds=value.get("maximum_snapshot_age_seconds"),
            license_disposition=value.get("license_disposition", ""),
            license_outcome=value.get("license_outcome", ""),
            outcome_precedence=tuple(value.get("outcome_precedence", ())),
            effective_from=value.get("effective_from", ""),
            effective_until=value.get("effective_until", ""),
            approval=(
                LegalPolicyApproval.from_dict(approval_value)
                if approval_value is not None
                else None
            ),
            schema_version=value.get(
                "schema_version", SANCTIONS_POLICY_SCHEMA_VERSION
            ),
        )


__all__ = [
    "AssociationEvidence",
    "AssociationKind",
    "COMPLIANCE_SCHEMA_VERSION",
    "CRYPTO_IR_COMPLIANCE_DOMAIN",
    "ComplianceModelError",
    "DesignationRecord",
    "DigitalCurrencyIdentifier",
    "Jurisdiction",
    "LegalPolicyApproval",
    "LicenseDisposition",
    "LicenseRecord",
    "OwnershipEvidence",
    "OwnershipInterest",
    "OwnershipKind",
    "PolicyRule",
    "SANCTIONS_POLICY_SCHEMA_VERSION",
    "SANCTIONS_SNAPSHOT_SCHEMA_VERSION",
    "SanctionsAuthority",
    "SanctionsList",
    "SanctionsMatch",
    "SanctionsPolicy",
    "SanctionsPolicyOutcome",
    "SanctionsProgram",
    "SanctionsSnapshot",
]
