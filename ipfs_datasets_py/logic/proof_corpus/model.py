"""Authority-grade attested proof envelope (AttestedProofEnvelope@1).

LIG-029 freezes the immutable proof-cache identity that later manifest,
revocation, applicability, and independent-verification leaves consume.

An envelope binds statement/assumption/obligation digests, domain and logic
family, result authority, source/corpus/policy/ontology/adapter/compiler/
translation/solver/reconstruction identities, proof/build/source-map CIDs,
attestation kind, circuit/VK/backend/public-input/security-profile bindings,
effective/expiry, jurisdiction/tenant/subject/resource scope, coverage,
parents, supersession/revocation references, and diagnostics.

Authority separation is fail-closed:

* ``direct-proof-verification`` is the only kind that may claim theorem
  authority by itself;
* ``verifier-execution`` is a distinct trusted-execution voucher and never
  silently upgrades to direct verification;
* ``artifact-membership``, optional signatures, and ``simulation`` remain
  non-substitutable for theorem proof (see :mod:`.policy`).

This leaf does not rewrite :mod:`.schemas`, :mod:`.store`, or :mod:`.attest`.
Legacy :class:`~.schemas.ArtifactEnvelope` rows stay valid storage envelopes;
authority-grade semantics live here as a composition layer.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ..ir_core.identity import cid_v1_from_digest
from ..ir_core.protocols import AuthorityKind
from .schemas import (
    ProofCorpusFamily,
    ProofCorpusIntegrityError,
    ProofCorpusSchemaError,
    parse_family,
)

ATTESTED_PROOF_ENVELOPE_INTERFACE: Final = "AttestedProofEnvelope@1"
ATTESTED_PROOF_ENVELOPE_SCHEMA_VERSION: Final = "attested-proof-envelope/v1"
SCOPE_BINDING_SCHEMA_VERSION: Final = "proof-scope-binding/v1"
CIRCUIT_BINDING_SCHEMA_VERSION: Final = "proof-circuit-binding/v1"
TEMPORAL_WINDOW_SCHEMA_VERSION: Final = "proof-temporal-window/v1"
COVERAGE_DECLARATION_SCHEMA_VERSION: Final = "proof-coverage-declaration/v1"
PIPELINE_IDENTITY_SCHEMA_VERSION: Final = "proof-pipeline-identity/v1"

_PROFILE_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_BARE_DIGEST_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_CID_RE: Final = re.compile(r"^b[a-z2-7]{10,200}$")

# Evidence classes that must never be treated as theorem proof by policy.
NON_AUTHORITATIVE_ATTESTATION_KINDS: Final[frozenset[str]] = frozenset(
    {
        "artifact-membership",
        "simulation",
    }
)

# Distinct non-proof evidence that may accompany an envelope but cannot
# substitute for direct verification (acceptance: signature non-substitution).
NON_SUBSTITUTABLE_EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "direct-proof-verification",
        "verifier-execution",
        "artifact-membership",
        "signature",
        "simulation",
    }
)

_ENVELOPE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "adapter_id",
        "assumption_digest",
        "attestation_kind",
        "backend_id",
        "build_manifest_cid",
        "circuit",
        "compiler_id",
        "content_cid",
        "content_digest",
        "corpus_root_cid",
        "coverage",
        "diagnostics",
        "domain",
        "envelope_cid",
        "family",
        "interface",
        "logic_family",
        "obligation_digest",
        "ontology_id",
        "parent_cids",
        "pipeline",
        "policy_id",
        "producer_id",
        "proof_artifact_cid",
        "proof_bytes_digest",
        "public_inputs",
        "reconstruction_id",
        "result_authority",
        "result_status",
        "revocation_cid",
        "revocation_root_cid",
        "schema_version",
        "scope",
        "security_profile",
        "signatures",
        "solver_id",
        "source_map_cid",
        "source_snapshot_cid",
        "statement_digest",
        "supersedes_cid",
        "supersession_cid",
        "temporal",
        "translation_id",
    }
)


class AttestedProofModelError(ProofCorpusSchemaError):
    """Raised when an authority-grade proof envelope is malformed."""


class AttestedProofIntegrityError(ProofCorpusIntegrityError):
    """Raised when envelope identity or authority bindings drift."""


class AttestationKind(str, Enum):
    """Closed attestation-kind vocabulary (plan §6.3).

    Kinds are intentionally non-hierarchical: membership, signature, and
    simulation never become direct proof verification by renaming.
    """

    DIRECT_PROOF_VERIFICATION = "direct-proof-verification"
    VERIFIER_EXECUTION = "verifier-execution"
    ARTIFACT_MEMBERSHIP = "artifact-membership"
    SIMULATION = "simulation"


class ProofResultStatus(str, Enum):
    """Bounded status labels for an attested proof envelope.

    Status is scoped by :attr:`AttestedProofEnvelope.result_authority` and
    never upgrades authority by itself.
    """

    PROVED = "proved"
    DISPROVED = "disproved"
    UNSATISFIABLE = "unsatisfiable"
    SATISFIABLE = "satisfiable"
    READY = "ready"
    NOT_READY = "not_ready"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    ERROR = "error"
    REVIEWED = "reviewed"
    ABSENT = "absent"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise AttestedProofModelError(
        f"value of type {type(value).__name__} is not JSON-serializable "
        "for the attested proof envelope"
    )


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AttestedProofModelError(f"{label} must be a mapping")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AttestedProofModelError(
            f"{field_name} must be a non-empty trimmed string"
        )
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, field_name)


def _require_digest(value: Any, field_name: str) -> str:
    digest = _require_text(value, field_name)
    if _BARE_DIGEST_RE.fullmatch(digest):
        digest = f"sha256:{digest}"
    if not _DIGEST_RE.fullmatch(digest):
        raise AttestedProofModelError(
            f"{field_name} must be a sha256:<hex> digest"
        )
    return digest


def _optional_digest(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_digest(value, field_name)


def _require_cid(value: Any, field_name: str) -> str:
    cid = _require_text(value, field_name)
    if not _CID_RE.fullmatch(cid):
        raise AttestedProofModelError(
            f"{field_name} must be a CIDv1 base32 string"
        )
    return cid


def _optional_cid(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_cid(value, field_name)


def _require_profile(value: Any, field_name: str = "security_profile") -> str:
    profile = _require_text(value, field_name)
    if not _PROFILE_RE.fullmatch(profile):
        raise AttestedProofModelError(
            f"{field_name} must be a lowercase hyphenated identifier"
        )
    return profile


def _optional_profile(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_profile(value, field_name)


def _require_identifier(value: Any, field_name: str) -> str:
    text = _require_text(value, field_name)
    if not _IDENTIFIER_RE.fullmatch(text):
        raise AttestedProofModelError(
            f"{field_name} must be a lowercase identifier "
            "(letters, digits, underscore)"
        )
    return text


def _optional_identifier(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_identifier(value, field_name)


def _unique_cids(values: Any, field_name: str) -> tuple[str, ...]:
    if values in (None, ()):
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise AttestedProofModelError(f"{field_name} must be a sequence of CIDs")
    try:
        items = tuple(_require_cid(item, field_name) for item in values)
    except TypeError as exc:
        raise AttestedProofModelError(
            f"{field_name} must be a sequence of CIDs"
        ) from exc
    if len(items) != len(set(items)):
        raise AttestedProofModelError(f"{field_name} values must be unique")
    return items


def _unique_texts(values: Any, field_name: str) -> tuple[str, ...]:
    if values in (None, ()):
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise AttestedProofModelError(
            f"{field_name} must be a sequence of strings"
        )
    try:
        items = tuple(_require_text(item, field_name) for item in values)
    except TypeError as exc:
        raise AttestedProofModelError(
            f"{field_name} must be a sequence of strings"
        ) from exc
    if len(items) != len(set(items)):
        raise AttestedProofModelError(f"{field_name} values must be unique")
    return items


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise AttestedProofModelError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _parse_enum(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise AttestedProofModelError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


def parse_attestation_kind(value: Any) -> AttestationKind:
    """Parse a closed attestation-kind wire value (fail closed)."""

    return _parse_enum(value, AttestationKind, "attestation_kind")  # type: ignore[return-value]


def parse_result_authority(value: Any) -> AuthorityKind:
    """Parse a result-authority kind (non-hierarchical closed set)."""

    if isinstance(value, AuthorityKind):
        # Collapse descriptive aliases onto the canonical enum member.
        return AuthorityKind(value.value)
    text = _require_text(value, "result_authority")
    try:
        return AuthorityKind(text)
    except ValueError as exc:
        allowed = ", ".join(
            sorted(
                {
                    AuthorityKind.THEOREM_PROOF.value,
                    AuthorityKind.SATISFIABILITY.value,
                    AuthorityKind.RUNTIME_MONITOR.value,
                    AuthorityKind.EVIDENCE_READINESS.value,
                    AuthorityKind.POLICY_APPROVAL.value,
                }
            )
        )
        raise AttestedProofModelError(
            f"result_authority must be one of: {allowed}"
        ) from exc


def attestation_kind_is_theorem_authoritative(kind: AttestationKind | str) -> bool:
    """Return whether *kind* may claim direct theorem verification.

    Membership, simulation, and signatures never qualify.  Verifier-execution
    is a distinct voucher and is not treated as direct proof verification.
    """

    parsed = parse_attestation_kind(kind)
    return parsed is AttestationKind.DIRECT_PROOF_VERIFICATION


def evidence_kinds_are_non_substitutable() -> frozenset[str]:
    """Return the closed set of evidence classes that remain non-substitutable.

    Direct verification, verifier execution, membership, signature, and
    simulation are distinct; none may silently become another.
    """

    return NON_SUBSTITUTABLE_EVIDENCE_KINDS


# ---------------------------------------------------------------------------
# Nested bindings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TemporalWindow:
    """Effective/expiry interval for an attested proof envelope."""

    effective_at: str = ""
    expires_at: str = ""
    schema_version: str = TEMPORAL_WINDOW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "effective_at", _optional_text(self.effective_at, "effective_at")
        )
        object.__setattr__(
            self, "expires_at", _optional_text(self.expires_at, "expires_at")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != TEMPORAL_WINDOW_SCHEMA_VERSION:
            raise AttestedProofModelError(
                f"unsupported temporal window schema: {self.schema_version!r}"
            )
        if (
            self.effective_at
            and self.expires_at
            and self.expires_at < self.effective_at
        ):
            raise AttestedProofModelError(
                "expires_at must not precede effective_at"
            )

    def is_effective_at(self, instant: str) -> bool:
        """Return whether *instant* falls inside the effective window."""

        instant = _require_text(instant, "instant")
        if self.effective_at and instant < self.effective_at:
            return False
        if self.expires_at and instant >= self.expires_at:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_at": self.effective_at,
            "expires_at": self.expires_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "TemporalWindow":
        if isinstance(value, TemporalWindow):
            return value
        payload = dict(_as_mapping(value, "temporal"))
        _reject_unknown(
            payload,
            frozenset({"effective_at", "expires_at", "schema_version"}),
            "temporal window",
        )
        return cls(
            effective_at=payload.get("effective_at", ""),
            expires_at=payload.get("expires_at", ""),
            schema_version=payload.get(
                "schema_version", TEMPORAL_WINDOW_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ScopeBinding:
    """Jurisdiction / tenant / subject / resource scope binding."""

    jurisdiction: str = ""
    tenant: str = ""
    subject_ids: tuple[str, ...] = ()
    resource_ids: tuple[str, ...] = ()
    purpose_ids: tuple[str, ...] = ()
    schema_version: str = SCOPE_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.jurisdiction not in ("", None):
            jurisdiction = _require_profile(self.jurisdiction, "jurisdiction")
        else:
            jurisdiction = ""
        object.__setattr__(self, "jurisdiction", jurisdiction)
        object.__setattr__(self, "tenant", _optional_text(self.tenant, "tenant"))
        object.__setattr__(
            self, "subject_ids", _unique_texts(self.subject_ids, "subject_ids")
        )
        object.__setattr__(
            self, "resource_ids", _unique_texts(self.resource_ids, "resource_ids")
        )
        object.__setattr__(
            self, "purpose_ids", _unique_texts(self.purpose_ids, "purpose_ids")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != SCOPE_BINDING_SCHEMA_VERSION:
            raise AttestedProofModelError(
                f"unsupported scope binding schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "jurisdiction": self.jurisdiction,
            "purpose_ids": list(self.purpose_ids),
            "resource_ids": list(self.resource_ids),
            "schema_version": self.schema_version,
            "subject_ids": list(self.subject_ids),
            "tenant": self.tenant,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ScopeBinding":
        if isinstance(value, ScopeBinding):
            return value
        payload = dict(_as_mapping(value, "scope"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "jurisdiction",
                    "purpose_ids",
                    "resource_ids",
                    "schema_version",
                    "subject_ids",
                    "tenant",
                }
            ),
            "scope binding",
        )
        return cls(
            jurisdiction=payload.get("jurisdiction", ""),
            tenant=payload.get("tenant", ""),
            subject_ids=tuple(payload.get("subject_ids", ())),
            resource_ids=tuple(payload.get("resource_ids", ())),
            purpose_ids=tuple(payload.get("purpose_ids", ())),
            schema_version=payload.get(
                "schema_version", SCOPE_BINDING_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class CircuitBinding:
    """Circuit / verification-key / backend / public-input binding."""

    circuit_id: str = ""
    circuit_version: int = 0
    circuit_digest: str = ""
    vk_id: str = ""
    vk_version: int = 0
    vk_digest: str = ""
    backend_id: str = ""
    proof_system: str = ""
    public_inputs: Mapping[str, Any] = field(default_factory=dict)
    security_profile: str = ""
    schema_version: str = CIRCUIT_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "circuit_id", _optional_text(self.circuit_id, "circuit_id")
        )
        if isinstance(self.circuit_version, bool) or not isinstance(
            self.circuit_version, int
        ):
            raise AttestedProofModelError("circuit_version must be an int")
        if self.circuit_version < 0:
            raise AttestedProofModelError(
                "circuit_version must be a non-negative int"
            )
        object.__setattr__(
            self,
            "circuit_digest",
            _optional_digest(self.circuit_digest, "circuit_digest"),
        )
        object.__setattr__(self, "vk_id", _optional_text(self.vk_id, "vk_id"))
        if isinstance(self.vk_version, bool) or not isinstance(self.vk_version, int):
            raise AttestedProofModelError("vk_version must be an int")
        if self.vk_version < 0:
            raise AttestedProofModelError("vk_version must be a non-negative int")
        object.__setattr__(
            self, "vk_digest", _optional_digest(self.vk_digest, "vk_digest")
        )
        object.__setattr__(
            self, "backend_id", _optional_text(self.backend_id, "backend_id")
        )
        object.__setattr__(
            self, "proof_system", _optional_text(self.proof_system, "proof_system")
        )
        public_inputs = dict(_as_mapping(self.public_inputs, "public_inputs"))
        object.__setattr__(
            self, "public_inputs", MappingProxyType(_json_ready(public_inputs))
        )
        object.__setattr__(
            self,
            "security_profile",
            _optional_profile(self.security_profile, "security_profile"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != CIRCUIT_BINDING_SCHEMA_VERSION:
            raise AttestedProofModelError(
                f"unsupported circuit binding schema: {self.schema_version!r}"
            )

    @property
    def circuit_ref(self) -> str:
        if not self.circuit_id:
            return ""
        if self.circuit_version <= 0:
            return self.circuit_id
        return f"{self.circuit_id}@v{self.circuit_version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "circuit_digest": self.circuit_digest,
            "circuit_id": self.circuit_id,
            "circuit_ref": self.circuit_ref,
            "circuit_version": self.circuit_version,
            "proof_system": self.proof_system,
            "public_inputs": _json_ready(dict(self.public_inputs)),
            "schema_version": self.schema_version,
            "security_profile": self.security_profile,
            "vk_digest": self.vk_digest,
            "vk_id": self.vk_id,
            "vk_version": self.vk_version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CircuitBinding":
        if isinstance(value, CircuitBinding):
            return value
        payload = dict(_as_mapping(value, "circuit"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "backend_id",
                    "circuit_digest",
                    "circuit_id",
                    "circuit_ref",
                    "circuit_version",
                    "proof_system",
                    "public_inputs",
                    "schema_version",
                    "security_profile",
                    "vk_digest",
                    "vk_id",
                    "vk_version",
                }
            ),
            "circuit binding",
        )
        return cls(
            circuit_id=payload.get("circuit_id", ""),
            circuit_version=int(payload.get("circuit_version", 0) or 0),
            circuit_digest=payload.get("circuit_digest", ""),
            vk_id=payload.get("vk_id", ""),
            vk_version=int(payload.get("vk_version", 0) or 0),
            vk_digest=payload.get("vk_digest", ""),
            backend_id=payload.get("backend_id", ""),
            proof_system=payload.get("proof_system", ""),
            public_inputs=dict(payload.get("public_inputs", {}) or {}),
            security_profile=payload.get("security_profile", ""),
            schema_version=payload.get(
                "schema_version", CIRCUIT_BINDING_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class PipelineIdentity:
    """Source / corpus / policy / ontology / adapter / compiler pipeline ids."""

    source_id: str = ""
    corpus_id: str = ""
    policy_id: str = ""
    ontology_id: str = ""
    adapter_id: str = ""
    compiler_id: str = ""
    translation_id: str = ""
    solver_id: str = ""
    reconstruction_id: str = ""
    schema_version: str = PIPELINE_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "source_id",
            "corpus_id",
            "policy_id",
            "ontology_id",
            "adapter_id",
            "compiler_id",
            "translation_id",
            "solver_id",
            "reconstruction_id",
        ):
            object.__setattr__(
                self, name, _optional_text(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PIPELINE_IDENTITY_SCHEMA_VERSION:
            raise AttestedProofModelError(
                f"unsupported pipeline identity schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "compiler_id": self.compiler_id,
            "corpus_id": self.corpus_id,
            "ontology_id": self.ontology_id,
            "policy_id": self.policy_id,
            "reconstruction_id": self.reconstruction_id,
            "schema_version": self.schema_version,
            "solver_id": self.solver_id,
            "source_id": self.source_id,
            "translation_id": self.translation_id,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "PipelineIdentity":
        if isinstance(value, PipelineIdentity):
            return value
        payload = dict(_as_mapping(value, "pipeline"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "adapter_id",
                    "compiler_id",
                    "corpus_id",
                    "ontology_id",
                    "policy_id",
                    "reconstruction_id",
                    "schema_version",
                    "solver_id",
                    "source_id",
                    "translation_id",
                }
            ),
            "pipeline identity",
        )
        return cls(
            source_id=payload.get("source_id", ""),
            corpus_id=payload.get("corpus_id", ""),
            policy_id=payload.get("policy_id", ""),
            ontology_id=payload.get("ontology_id", ""),
            adapter_id=payload.get("adapter_id", ""),
            compiler_id=payload.get("compiler_id", ""),
            translation_id=payload.get("translation_id", ""),
            solver_id=payload.get("solver_id", ""),
            reconstruction_id=payload.get("reconstruction_id", ""),
            schema_version=payload.get(
                "schema_version", PIPELINE_IDENTITY_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class CoverageDeclaration:
    """Evidence-coverage declaration bound into an envelope."""

    covered_selectors: tuple[str, ...] = ()
    gap_kinds: tuple[str, ...] = ()
    complete: bool = False
    notes: str = ""
    schema_version: str = COVERAGE_DECLARATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "covered_selectors",
            _unique_texts(self.covered_selectors, "covered_selectors"),
        )
        object.__setattr__(
            self, "gap_kinds", _unique_texts(self.gap_kinds, "gap_kinds")
        )
        if not isinstance(self.complete, bool):
            raise AttestedProofModelError("complete must be a bool")
        if self.complete and self.gap_kinds:
            raise AttestedProofModelError(
                "complete coverage cannot declare gap_kinds"
            )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != COVERAGE_DECLARATION_SCHEMA_VERSION:
            raise AttestedProofModelError(
                f"unsupported coverage declaration schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "covered_selectors": list(self.covered_selectors),
            "gap_kinds": list(self.gap_kinds),
            "notes": self.notes,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CoverageDeclaration":
        if isinstance(value, CoverageDeclaration):
            return value
        payload = dict(_as_mapping(value, "coverage"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "complete",
                    "covered_selectors",
                    "gap_kinds",
                    "notes",
                    "schema_version",
                }
            ),
            "coverage declaration",
        )
        return cls(
            covered_selectors=tuple(payload.get("covered_selectors", ())),
            gap_kinds=tuple(payload.get("gap_kinds", ())),
            complete=bool(payload.get("complete", False)),
            notes=payload.get("notes", ""),
            schema_version=payload.get(
                "schema_version", COVERAGE_DECLARATION_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AttestedProofEnvelope:
    """Immutable authority-grade proof envelope (AttestedProofEnvelope@1).

    Identity is content-addressed over the canonical authority payload.  Load
    paths rehash and fail closed on drift.  Legacy incomplete records without
    statement/assumption/obligation digests and attestation kind cannot be
    constructed (they are non-authoritative and must migrate explicitly).
    """

    statement_digest: str
    assumption_digest: str
    obligation_digest: str
    domain: str
    logic_family: str
    result_authority: AuthorityKind
    attestation_kind: AttestationKind
    family: ProofCorpusFamily | str = ProofCorpusFamily.LEGAL
    result_status: ProofResultStatus | str = ProofResultStatus.UNKNOWN
    proof_artifact_cid: str = ""
    proof_bytes_digest: str = ""
    source_snapshot_cid: str = ""
    corpus_root_cid: str = ""
    revocation_root_cid: str = ""
    policy_id: str = ""
    ontology_id: str = ""
    adapter_id: str = ""
    compiler_id: str = ""
    translation_id: str = ""
    solver_id: str = ""
    reconstruction_id: str = ""
    build_manifest_cid: str = ""
    source_map_cid: str = ""
    backend_id: str = ""
    security_profile: str = ""
    public_inputs: Mapping[str, Any] = field(default_factory=dict)
    circuit: CircuitBinding | Mapping[str, Any] | None = None
    pipeline: PipelineIdentity | Mapping[str, Any] | None = None
    scope: ScopeBinding | Mapping[str, Any] | None = None
    temporal: TemporalWindow | Mapping[str, Any] | None = None
    coverage: CoverageDeclaration | Mapping[str, Any] | None = None
    parent_cids: tuple[str, ...] = ()
    supersedes_cid: str = ""
    supersession_cid: str = ""
    revocation_cid: str = ""
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    signatures: tuple[Mapping[str, Any], ...] = ()
    producer_id: str = ""
    content_digest: str = ""
    content_cid: str = ""
    envelope_cid: str = ""
    schema_version: str = ATTESTED_PROOF_ENVELOPE_SCHEMA_VERSION
    interface: str = ATTESTED_PROOF_ENVELOPE_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "statement_digest",
            _require_digest(self.statement_digest, "statement_digest"),
        )
        object.__setattr__(
            self,
            "assumption_digest",
            _require_digest(self.assumption_digest, "assumption_digest"),
        )
        object.__setattr__(
            self,
            "obligation_digest",
            _require_digest(self.obligation_digest, "obligation_digest"),
        )
        object.__setattr__(
            self, "domain", _require_identifier(self.domain, "domain")
        )
        object.__setattr__(
            self,
            "logic_family",
            _require_identifier(self.logic_family, "logic_family"),
        )
        object.__setattr__(
            self,
            "result_authority",
            parse_result_authority(self.result_authority),
        )
        object.__setattr__(
            self,
            "attestation_kind",
            parse_attestation_kind(self.attestation_kind),
        )
        object.__setattr__(self, "family", parse_family(self.family))
        object.__setattr__(
            self,
            "result_status",
            _parse_enum(self.result_status, ProofResultStatus, "result_status"),
        )

        object.__setattr__(
            self,
            "proof_artifact_cid",
            _optional_cid(self.proof_artifact_cid, "proof_artifact_cid"),
        )
        object.__setattr__(
            self,
            "proof_bytes_digest",
            _optional_digest(self.proof_bytes_digest, "proof_bytes_digest"),
        )
        object.__setattr__(
            self,
            "source_snapshot_cid",
            _optional_cid(self.source_snapshot_cid, "source_snapshot_cid"),
        )
        object.__setattr__(
            self,
            "corpus_root_cid",
            _optional_cid(self.corpus_root_cid, "corpus_root_cid"),
        )
        object.__setattr__(
            self,
            "revocation_root_cid",
            _optional_cid(self.revocation_root_cid, "revocation_root_cid"),
        )
        for name in (
            "policy_id",
            "ontology_id",
            "adapter_id",
            "compiler_id",
            "translation_id",
            "solver_id",
            "reconstruction_id",
            "backend_id",
            "producer_id",
        ):
            object.__setattr__(
                self, name, _optional_text(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "build_manifest_cid",
            _optional_cid(self.build_manifest_cid, "build_manifest_cid"),
        )
        object.__setattr__(
            self,
            "source_map_cid",
            _optional_cid(self.source_map_cid, "source_map_cid"),
        )
        object.__setattr__(
            self,
            "security_profile",
            _optional_profile(self.security_profile, "security_profile"),
        )
        public_inputs = dict(_as_mapping(self.public_inputs, "public_inputs"))
        object.__setattr__(
            self, "public_inputs", MappingProxyType(_json_ready(public_inputs))
        )

        circuit = self.circuit
        if circuit is None:
            circuit = CircuitBinding(
                backend_id=self.backend_id,
                public_inputs=dict(self.public_inputs),
                security_profile=self.security_profile,
            )
        elif not isinstance(circuit, CircuitBinding):
            circuit = CircuitBinding.from_dict(circuit)
        # Prefer explicit top-level security/backend when circuit omits them.
        if self.backend_id and not circuit.backend_id:
            circuit = CircuitBinding.from_dict(
                {**circuit.to_dict(), "backend_id": self.backend_id}
            )
        if self.security_profile and not circuit.security_profile:
            circuit = CircuitBinding.from_dict(
                {
                    **circuit.to_dict(),
                    "security_profile": self.security_profile,
                }
            )
        if self.public_inputs and not circuit.public_inputs:
            circuit = CircuitBinding.from_dict(
                {
                    **circuit.to_dict(),
                    "public_inputs": dict(self.public_inputs),
                }
            )
        object.__setattr__(self, "circuit", circuit)
        # Mirror circuit fields onto top-level for policy allowlists.
        if circuit.backend_id and not self.backend_id:
            object.__setattr__(self, "backend_id", circuit.backend_id)
        if circuit.security_profile and not self.security_profile:
            object.__setattr__(
                self, "security_profile", circuit.security_profile
            )

        pipeline = self.pipeline
        if pipeline is None:
            pipeline = PipelineIdentity(
                policy_id=self.policy_id,
                ontology_id=self.ontology_id,
                adapter_id=self.adapter_id,
                compiler_id=self.compiler_id,
                translation_id=self.translation_id,
                solver_id=self.solver_id,
                reconstruction_id=self.reconstruction_id,
            )
        elif not isinstance(pipeline, PipelineIdentity):
            pipeline = PipelineIdentity.from_dict(pipeline)
        object.__setattr__(self, "pipeline", pipeline)
        # Keep top-level pipeline ids in sync for wire consumers.
        for name in (
            "policy_id",
            "ontology_id",
            "adapter_id",
            "compiler_id",
            "translation_id",
            "solver_id",
            "reconstruction_id",
        ):
            pipeline_value = getattr(pipeline, name)
            if pipeline_value and not getattr(self, name):
                object.__setattr__(self, name, pipeline_value)

        scope = self.scope
        if scope is None:
            scope = ScopeBinding()
        elif not isinstance(scope, ScopeBinding):
            scope = ScopeBinding.from_dict(scope)
        object.__setattr__(self, "scope", scope)

        temporal = self.temporal
        if temporal is None:
            temporal = TemporalWindow()
        elif not isinstance(temporal, TemporalWindow):
            temporal = TemporalWindow.from_dict(temporal)
        object.__setattr__(self, "temporal", temporal)

        coverage = self.coverage
        if coverage is None:
            coverage = CoverageDeclaration()
        elif not isinstance(coverage, CoverageDeclaration):
            coverage = CoverageDeclaration.from_dict(coverage)
        object.__setattr__(self, "coverage", coverage)

        object.__setattr__(
            self, "parent_cids", _unique_cids(self.parent_cids, "parent_cids")
        )
        object.__setattr__(
            self,
            "supersedes_cid",
            _optional_cid(self.supersedes_cid, "supersedes_cid"),
        )
        object.__setattr__(
            self,
            "supersession_cid",
            _optional_cid(self.supersession_cid, "supersession_cid"),
        )
        object.__setattr__(
            self,
            "revocation_cid",
            _optional_cid(self.revocation_cid, "revocation_cid"),
        )
        diagnostics = dict(_as_mapping(self.diagnostics, "diagnostics"))
        object.__setattr__(
            self, "diagnostics", MappingProxyType(_json_ready(diagnostics))
        )

        if self.signatures in (None, ()):
            signatures: tuple[Mapping[str, Any], ...] = ()
        else:
            if isinstance(self.signatures, (str, bytes, bytearray, Mapping)):
                raise AttestedProofModelError(
                    "signatures must be a sequence of mappings"
                )
            try:
                signatures = tuple(
                    MappingProxyType(
                        _json_ready(dict(_as_mapping(item, "signature")))
                    )
                    for item in self.signatures
                )
            except TypeError as exc:
                raise AttestedProofModelError(
                    "signatures must be a sequence of mappings"
                ) from exc
        object.__setattr__(self, "signatures", signatures)

        if self.schema_version != ATTESTED_PROOF_ENVELOPE_SCHEMA_VERSION:
            raise AttestedProofModelError(
                f"unsupported attested proof envelope schema: "
                f"{self.schema_version!r}"
            )
        if self.interface != ATTESTED_PROOF_ENVELOPE_INTERFACE:
            raise AttestedProofModelError(
                f"unsupported attested proof envelope interface: "
                f"{self.interface!r}"
            )

        # Simulation must never silently claim theorem authority via status.
        if (
            self.attestation_kind is AttestationKind.SIMULATION
            and self.result_authority is AuthorityKind.THEOREM_PROOF
            and self.result_status is ProofResultStatus.PROVED
        ):
            raise AttestedProofIntegrityError(
                "simulation attestation cannot claim theorem_proof proved status"
            )

        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest:
            recorded = _require_digest(self.content_digest, "content_digest")
            if recorded != digest:
                raise AttestedProofIntegrityError(
                    "envelope content_digest does not match payload"
                )
        if self.content_cid:
            recorded_cid = _require_cid(self.content_cid, "content_cid")
            if recorded_cid != cid:
                raise AttestedProofIntegrityError(
                    "envelope content_cid does not match payload"
                )
        if self.envelope_cid:
            recorded_env = _require_cid(self.envelope_cid, "envelope_cid")
            if recorded_env != cid:
                raise AttestedProofIntegrityError(
                    "envelope_cid does not match payload"
                )
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)
        object.__setattr__(self, "envelope_cid", cid)

    # -- authority predicates -------------------------------------------------

    @property
    def is_simulated(self) -> bool:
        return self.attestation_kind is AttestationKind.SIMULATION

    @property
    def is_membership_only(self) -> bool:
        return self.attestation_kind is AttestationKind.ARTIFACT_MEMBERSHIP

    @property
    def has_signature_evidence(self) -> bool:
        return bool(self.signatures)

    @property
    def claims_direct_verification(self) -> bool:
        return (
            self.attestation_kind is AttestationKind.DIRECT_PROOF_VERIFICATION
        )

    @property
    def claims_verifier_execution(self) -> bool:
        return self.attestation_kind is AttestationKind.VERIFIER_EXECUTION

    def is_theorem_authoritative(self) -> bool:
        """Return whether this envelope may be treated as theorem authority.

        Direct proof verification with theorem-proof authority is required.
        Membership, signature, simulation, and verifier-execution alone never
        qualify (policy may still accept verifier-execution under an explicit
        allowlist; that decision lives in :mod:`.policy`).
        """

        if self.result_authority is not AuthorityKind.THEOREM_PROOF:
            return False
        if not attestation_kind_is_theorem_authoritative(self.attestation_kind):
            return False
        if self.is_simulated or self.is_membership_only:
            return False
        return True

    def non_substitutable_evidence_classes(self) -> frozenset[str]:
        """Evidence classes present on this envelope that remain non-substitutable."""

        present: set[str] = {self.attestation_kind.value}
        if self.has_signature_evidence:
            present.add("signature")
        return frozenset(present) & NON_SUBSTITUTABLE_EVIDENCE_KINDS

    def is_revoked(self) -> bool:
        return bool(self.revocation_cid)

    def is_superseded(self) -> bool:
        return bool(self.supersession_cid)

    def is_effective_at(self, instant: str) -> bool:
        if self.is_revoked() or self.is_superseded():
            return False
        return self.temporal.is_effective_at(instant)

    # -- identity / serialization --------------------------------------------

    def _identity_payload(self) -> dict[str, Any]:
        assert isinstance(self.circuit, CircuitBinding)
        assert isinstance(self.pipeline, PipelineIdentity)
        assert isinstance(self.scope, ScopeBinding)
        assert isinstance(self.temporal, TemporalWindow)
        assert isinstance(self.coverage, CoverageDeclaration)
        return {
            "adapter_id": self.adapter_id,
            "assumption_digest": self.assumption_digest,
            "attestation_kind": self.attestation_kind.value,
            "backend_id": self.backend_id,
            "build_manifest_cid": self.build_manifest_cid,
            "circuit": self.circuit.to_dict(),
            "compiler_id": self.compiler_id,
            "corpus_root_cid": self.corpus_root_cid,
            "coverage": self.coverage.to_dict(),
            "diagnostics": _json_ready(dict(self.diagnostics)),
            "domain": self.domain,
            "family": self.family.value,
            "interface": self.interface,
            "logic_family": self.logic_family,
            "obligation_digest": self.obligation_digest,
            "ontology_id": self.ontology_id,
            "parent_cids": list(self.parent_cids),
            "pipeline": self.pipeline.to_dict(),
            "policy_id": self.policy_id,
            "producer_id": self.producer_id,
            "proof_artifact_cid": self.proof_artifact_cid,
            "proof_bytes_digest": self.proof_bytes_digest,
            "public_inputs": _json_ready(dict(self.public_inputs)),
            "reconstruction_id": self.reconstruction_id,
            "result_authority": self.result_authority.value,
            "result_status": self.result_status.value,
            "revocation_cid": self.revocation_cid,
            "revocation_root_cid": self.revocation_root_cid,
            "schema_version": self.schema_version,
            "scope": self.scope.to_dict(),
            "security_profile": self.security_profile,
            "signatures": [_json_ready(dict(item)) for item in self.signatures],
            "solver_id": self.solver_id,
            "source_map_cid": self.source_map_cid,
            "source_snapshot_cid": self.source_snapshot_cid,
            "statement_digest": self.statement_digest,
            "supersedes_cid": self.supersedes_cid,
            "supersession_cid": self.supersession_cid,
            "temporal": self.temporal.to_dict(),
            "translation_id": self.translation_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        payload["envelope_cid"] = self.envelope_cid
        return payload

    def identity_digest(self) -> str:
        """Return the canonical content digest (``sha256:<hex>``)."""

        return self.content_digest

    def verify_integrity(self) -> "AttestedProofEnvelope":
        """Recompute identity; fail closed on digest/CID drift."""

        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if digest != self.content_digest:
            raise AttestedProofIntegrityError(
                "content_digest does not match recomputed identity"
            )
        if cid != self.content_cid or cid != self.envelope_cid:
            raise AttestedProofIntegrityError(
                "content_cid/envelope_cid does not match recomputed identity"
            )
        return self

    @classmethod
    def from_dict(cls, value: Any) -> "AttestedProofEnvelope":
        payload = dict(_as_mapping(value, "attested proof envelope"))
        _reject_unknown(payload, _ENVELOPE_FIELDS, "attested proof envelope")
        return cls(
            statement_digest=payload.get("statement_digest", ""),
            assumption_digest=payload.get("assumption_digest", ""),
            obligation_digest=payload.get("obligation_digest", ""),
            domain=payload.get("domain", ""),
            logic_family=payload.get("logic_family", ""),
            result_authority=payload.get("result_authority", ""),
            attestation_kind=payload.get("attestation_kind", ""),
            family=payload.get("family", ProofCorpusFamily.LEGAL.value),
            result_status=payload.get(
                "result_status", ProofResultStatus.UNKNOWN.value
            ),
            proof_artifact_cid=payload.get("proof_artifact_cid", ""),
            proof_bytes_digest=payload.get("proof_bytes_digest", ""),
            source_snapshot_cid=payload.get("source_snapshot_cid", ""),
            corpus_root_cid=payload.get("corpus_root_cid", ""),
            revocation_root_cid=payload.get("revocation_root_cid", ""),
            policy_id=payload.get("policy_id", ""),
            ontology_id=payload.get("ontology_id", ""),
            adapter_id=payload.get("adapter_id", ""),
            compiler_id=payload.get("compiler_id", ""),
            translation_id=payload.get("translation_id", ""),
            solver_id=payload.get("solver_id", ""),
            reconstruction_id=payload.get("reconstruction_id", ""),
            build_manifest_cid=payload.get("build_manifest_cid", ""),
            source_map_cid=payload.get("source_map_cid", ""),
            backend_id=payload.get("backend_id", ""),
            security_profile=payload.get("security_profile", ""),
            public_inputs=dict(payload.get("public_inputs", {}) or {}),
            circuit=payload.get("circuit"),
            pipeline=payload.get("pipeline"),
            scope=payload.get("scope"),
            temporal=payload.get("temporal"),
            coverage=payload.get("coverage"),
            parent_cids=tuple(payload.get("parent_cids", ()) or ()),
            supersedes_cid=payload.get("supersedes_cid", ""),
            supersession_cid=payload.get("supersession_cid", ""),
            revocation_cid=payload.get("revocation_cid", ""),
            diagnostics=dict(payload.get("diagnostics", {}) or {}),
            signatures=tuple(payload.get("signatures", ()) or ()),
            producer_id=payload.get("producer_id", ""),
            content_digest=payload.get("content_digest", ""),
            content_cid=payload.get("content_cid", ""),
            envelope_cid=payload.get("envelope_cid", ""),
            schema_version=payload.get(
                "schema_version", ATTESTED_PROOF_ENVELOPE_SCHEMA_VERSION
            ),
            interface=payload.get(
                "interface", ATTESTED_PROOF_ENVELOPE_INTERFACE
            ),
        )


def build_attested_proof_envelope(**kwargs: Any) -> AttestedProofEnvelope:
    """Construct a validated :class:`AttestedProofEnvelope` (keyword sugar)."""

    return AttestedProofEnvelope(**kwargs)


__all__ = [
    "ATTESTED_PROOF_ENVELOPE_INTERFACE",
    "ATTESTED_PROOF_ENVELOPE_SCHEMA_VERSION",
    "CIRCUIT_BINDING_SCHEMA_VERSION",
    "COVERAGE_DECLARATION_SCHEMA_VERSION",
    "NON_AUTHORITATIVE_ATTESTATION_KINDS",
    "NON_SUBSTITUTABLE_EVIDENCE_KINDS",
    "PIPELINE_IDENTITY_SCHEMA_VERSION",
    "SCOPE_BINDING_SCHEMA_VERSION",
    "TEMPORAL_WINDOW_SCHEMA_VERSION",
    "AttestationKind",
    "AttestedProofEnvelope",
    "AttestedProofIntegrityError",
    "AttestedProofModelError",
    "CircuitBinding",
    "CoverageDeclaration",
    "PipelineIdentity",
    "ProofResultStatus",
    "ScopeBinding",
    "TemporalWindow",
    "attestation_kind_is_theorem_authoritative",
    "build_attested_proof_envelope",
    "evidence_kinds_are_non_substitutable",
    "parse_attestation_kind",
    "parse_result_authority",
]
