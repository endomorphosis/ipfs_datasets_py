"""Independent consumer verification of selected proof evidence (LIG-032).

Interfaces:

* ``AttestedProofVerifier@1`` — consumer-side verifier that re-checks every
  selected body / native proof / ZKP / parent / source / policy / scope / time
  / revocation binding against exact corpus and revocation roots.
* ``SelectedEvidencePack@1`` — content-addressed pack of selected evidence
  items plus a consumer verification receipt.

Authority rules (acceptance / plan §6.3 / LIG-G100):

* Exact roots and full statement/assumption/obligation/source/build/compiler/
  solver/translation/reconstruction/proof bindings are required.
* Approved native or ZK proof evidence, circuit spec/VK/public inputs, and
  tenant/scope/time/expiry/supersession/revocation/coverage/parents are
  independently verified by the consumer — never delegated to producer claims
  or cache hits alone.
* Reject unknown/downgraded algorithms, malformed/underconstrained/forged
  proofs, real-to-simulation fallback, membership-as-theorem, partial fetch,
  and cross-tenant substitution.

This leaf does not rewrite :mod:`.model`, :mod:`.policy`, :mod:`.store`,
:mod:`.attest`, :mod:`.manifest`, or :mod:`.revocation`.
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
from .model import (
    AttestationKind,
    AttestedProofEnvelope,
    AttestedProofIntegrityError,
    AttestedProofModelError,
    CircuitBinding,
    CoverageDeclaration,
    ScopeBinding,
    TemporalWindow,
    attestation_kind_is_theorem_authoritative,
)
from .policy import (
    ProofTrustPolicy,
    TrustEvaluationStatus,
)

ATTESTED_PROOF_VERIFIER_INTERFACE: Final = "AttestedProofVerifier@1"
ATTESTED_PROOF_VERIFIER_SCHEMA_VERSION: Final = "attested-proof-verifier/v1"
SELECTED_EVIDENCE_PACK_INTERFACE: Final = "SelectedEvidencePack@1"
SELECTED_EVIDENCE_PACK_SCHEMA_VERSION: Final = "selected-evidence-pack/v1"
SELECTED_EVIDENCE_ITEM_SCHEMA_VERSION: Final = "selected-evidence-item/v1"
CONSUMER_VERIFICATION_RECEIPT_SCHEMA_VERSION: Final = (
    "consumer-verification-receipt/v1"
)
ITEM_VERIFICATION_RESULT_SCHEMA_VERSION: Final = (
    "item-verification-result/v1"
)
VERIFIER_CONTEXT_SCHEMA_VERSION: Final = "proof-verifier-context/v1"

_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_BARE_DIGEST_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_CID_RE: Final = re.compile(r"^b[a-z2-7]{10,200}$")
_PROFILE_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")

# Closed set of authority bindings the consumer must observe on every selected
# authoritative item (acceptance: "all ... bindings").
REQUIRED_AUTHORITY_BINDINGS: Final[tuple[str, ...]] = (
    "statement_digest",
    "assumption_digest",
    "obligation_digest",
    "source_snapshot_cid",
    "build_manifest_cid",
    "compiler_id",
    "solver_id",
    "translation_id",
    "reconstruction_id",
    "proof_artifact_cid",
    "proof_bytes_digest",
    "corpus_root_cid",
    "revocation_root_cid",
    "policy_id",
    "attestation_kind",
    "result_authority",
    "circuit.circuit_id",
    "circuit.circuit_digest",
    "circuit.vk_id",
    "circuit.vk_digest",
    "circuit.public_inputs",
    "public_inputs",
    "scope.tenant",
    "scope.jurisdiction",
    "temporal.effective_at",
    "temporal.expires_at",
    "coverage",
    "parent_cids",
    "security_profile",
    "backend_id",
)

# Stable rejection reason codes (acceptance vocabulary).
REASON_PRODUCER_CLAIM: Final = "producer_claim_not_authority"
REASON_CACHE_HIT: Final = "cache_hit_not_authority"
REASON_UNKNOWN_ALGORITHM: Final = "unknown_algorithm"
REASON_ALGORITHM_DOWNGRADED: Final = "algorithm_downgraded"
REASON_MALFORMED_PROOF: Final = "malformed_proof"
REASON_UNDERCONSTRAINED: Final = "underconstrained_proof"
REASON_FORGED_PROOF: Final = "forged_proof"
REASON_REAL_TO_SIM: Final = "real_to_simulation_fallback"
REASON_MEMBERSHIP_THEOREM: Final = "membership_as_theorem"
REASON_PARTIAL_FETCH: Final = "partial_fetch"
REASON_CROSS_TENANT: Final = "cross_tenant_substitution"
REASON_ROOT_MISMATCH: Final = "root_mismatch"
REASON_MISSING_BINDING: Final = "missing_binding"
REASON_REVOKED: Final = "envelope_revoked"
REASON_SUPERSEDED: Final = "envelope_superseded"
REASON_EXPIRED: Final = "envelope_not_effective"
REASON_INTEGRITY: Final = "integrity_failure"
REASON_PUBLIC_INPUTS: Final = "public_input_mismatch"
REASON_CIRCUIT_VK: Final = "circuit_vk_mismatch"
REASON_NATIVE_DIGEST: Final = "native_proof_digest_mismatch"
REASON_ZK_FAILED: Final = "zk_verification_failed"
REASON_ZK_SIMULATED: Final = "zk_simulated_rejected"
REASON_MISSING_PROOF: Final = "missing_proof_evidence"
REASON_TRUST_POLICY: Final = "trust_policy_rejected"
REASON_PARENT_MISSING: Final = "parent_binding_missing"
REASON_PARENT_MISMATCH: Final = "parent_binding_mismatch"
REASON_COVERAGE_INCOMPLETE: Final = "coverage_incomplete"
REASON_UNKNOWN_BACKEND: Final = "unknown_backend"
REASON_SIMULATION_AUTHORITY: Final = "simulation_not_authority"

# Default approved native/ZK algorithms for production verification.
DEFAULT_APPROVED_PROOF_SYSTEMS: Final[frozenset[str]] = frozenset(
    {
        "groth16",
        "plonk",
        "native-smt",
        "native-lean",
        "native-z3",
    }
)
DEFAULT_APPROVED_BACKENDS: Final[frozenset[str]] = frozenset(
    {
        "provekit",
        "groth16",
        "native",
        "z3",
        "lean",
    }
)

# Simulated / non-production algorithm labels that must not authorize.
_SIMULATED_ALGORITHM_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "simulated",
        "simulation",
        "mock",
        "fake",
        "dummy",
        "test-only",
    }
)


class ProofVerifierError(AttestedProofModelError):
    """Raised when a verifier operation cannot proceed safely."""


class ProofVerifierIntegrityError(AttestedProofIntegrityError, ProofVerifierError):
    """Raised when selected evidence fails integrity or receipt binding."""


class VerificationStatus(str, Enum):
    """Outcome of consumer verification for an item or pack."""

    PASS = "pass"
    REJECT = "reject"
    FAIL = "fail"


class ProofEvidenceKind(str, Enum):
    """How proof material is presented to the consumer verifier."""

    NATIVE = "native"
    ZK = "zk"
    BOTH = "both"
    NONE = "none"


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
    if isinstance(value, (bytes, bytearray)):
        return "sha256:" + hashlib.sha256(bytes(value)).hexdigest()
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
    raise ProofVerifierError(
        f"value of type {type(value).__name__} is not JSON-serializable "
        "for the proof verifier"
    )


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProofVerifierError(f"{label} must be a mapping")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProofVerifierError(
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
        raise ProofVerifierError(
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
        raise ProofVerifierError(
            f"{field_name} must be a CIDv1 base32 string"
        )
    return cid


def _optional_cid(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_cid(value, field_name)


def _unique_texts(values: Any, field_name: str) -> tuple[str, ...]:
    if values in (None, ()):
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise ProofVerifierError(
            f"{field_name} must be a sequence of strings"
        )
    try:
        items = tuple(_require_text(item, field_name) for item in values)
    except TypeError as exc:
        raise ProofVerifierError(
            f"{field_name} must be a sequence of strings"
        ) from exc
    if len(items) != len(set(items)):
        raise ProofVerifierError(f"{field_name} values must be unique")
    return items


def _unique_cids(values: Any, field_name: str) -> tuple[str, ...]:
    if values in (None, ()):
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise ProofVerifierError(f"{field_name} must be a sequence of CIDs")
    try:
        items = tuple(_require_cid(item, field_name) for item in values)
    except TypeError as exc:
        raise ProofVerifierError(
            f"{field_name} must be a sequence of CIDs"
        ) from exc
    if len(items) != len(set(items)):
        raise ProofVerifierError(f"{field_name} values must be unique")
    return items


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProofVerifierError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _parse_enum(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ProofVerifierError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


def _normalize_bytes(value: Any, field_name: str) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        # Accept hex or utf-8 text payloads.
        text = value.strip()
        if re.fullmatch(r"[0-9a-fA-F]+", text) and len(text) % 2 == 0:
            try:
                return bytes.fromhex(text)
            except ValueError as exc:
                raise ProofVerifierError(
                    f"{field_name} is not valid hex"
                ) from exc
        return text.encode("utf-8")
    raise ProofVerifierError(
        f"{field_name} must be bytes, hex, or utf-8 text"
    )


def digest_of_bytes(data: bytes) -> str:
    """Return ``sha256:<hex>`` for *data*."""

    return _sha256_digest(data)


def binding_value(envelope: AttestedProofEnvelope, binding: str) -> Any:
    """Resolve a dotted binding path on *envelope* (read-only)."""

    if binding == "coverage":
        coverage = envelope.coverage
        assert isinstance(coverage, CoverageDeclaration)
        # Present if coverage is declared (even incomplete).
        return coverage.to_dict() if coverage.covered_selectors or coverage.complete else ""
    if binding == "parent_cids":
        return envelope.parent_cids
    if binding == "public_inputs":
        return dict(envelope.public_inputs)
    if binding == "attestation_kind":
        return envelope.attestation_kind.value
    if binding == "result_authority":
        return envelope.result_authority.value
    if "." in binding:
        head, tail = binding.split(".", 1)
        nested = getattr(envelope, head, None)
        if nested is None:
            return ""
        if tail == "public_inputs":
            return dict(getattr(nested, "public_inputs", {}) or {})
        return getattr(nested, tail, "")
    return getattr(envelope, binding, "")


def is_binding_present(value: Any) -> bool:
    """Return whether a resolved binding value is non-empty."""

    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (str, bytes, bytearray)):
        return bool(value)
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Sequence):
        return bool(value)
    return bool(value)


def absent_authority_bindings(
    envelope: AttestedProofEnvelope,
    *,
    required: Sequence[str] = REQUIRED_AUTHORITY_BINDINGS,
) -> tuple[str, ...]:
    """Return required authority bindings that are absent on *envelope*."""

    missing: list[str] = []
    for binding in required:
        if not is_binding_present(binding_value(envelope, binding)):
            missing.append(binding)
    return tuple(missing)


def _algorithm_is_simulated(label: str) -> bool:
    lowered = label.strip().lower()
    if not lowered:
        return False
    if lowered in _SIMULATED_ALGORITHM_MARKERS:
        return True
    return any(marker in lowered for marker in _SIMULATED_ALGORITHM_MARKERS)


# ---------------------------------------------------------------------------
# Context / items / results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerifierContext:
    """Exact-root and scope context the consumer re-verifies against."""

    corpus_root_cid: str
    revocation_root_cid: str = ""
    expected_tenant: str = ""
    expected_jurisdiction: str = ""
    at_time: str = ""
    approved_proof_systems: tuple[str, ...] = tuple(
        sorted(DEFAULT_APPROVED_PROOF_SYSTEMS)
    )
    approved_backends: tuple[str, ...] = tuple(sorted(DEFAULT_APPROVED_BACKENDS))
    revoked_envelope_cids: tuple[str, ...] = ()
    accept_simulated: bool = False
    require_native_or_zk: bool = True
    require_complete_coverage: bool = True
    trust_policy: ProofTrustPolicy | None = None
    schema_version: str = VERIFIER_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "corpus_root_cid",
            _require_cid(self.corpus_root_cid, "corpus_root_cid"),
        )
        object.__setattr__(
            self,
            "revocation_root_cid",
            _optional_cid(self.revocation_root_cid, "revocation_root_cid"),
        )
        object.__setattr__(
            self,
            "expected_tenant",
            _optional_text(self.expected_tenant, "expected_tenant"),
        )
        object.__setattr__(
            self,
            "expected_jurisdiction",
            _optional_text(self.expected_jurisdiction, "expected_jurisdiction"),
        )
        object.__setattr__(
            self, "at_time", _optional_text(self.at_time, "at_time")
        )
        object.__setattr__(
            self,
            "approved_proof_systems",
            _unique_texts(
                self.approved_proof_systems, "approved_proof_systems"
            ),
        )
        object.__setattr__(
            self,
            "approved_backends",
            _unique_texts(self.approved_backends, "approved_backends"),
        )
        object.__setattr__(
            self,
            "revoked_envelope_cids",
            _unique_cids(
                self.revoked_envelope_cids, "revoked_envelope_cids"
            ),
        )
        for flag_name in (
            "accept_simulated",
            "require_native_or_zk",
            "require_complete_coverage",
        ):
            if not isinstance(getattr(self, flag_name), bool):
                raise ProofVerifierError(f"{flag_name} must be a bool")
        if self.trust_policy is not None and not isinstance(
            self.trust_policy, ProofTrustPolicy
        ):
            raise ProofVerifierError(
                "trust_policy must be a ProofTrustPolicy or None"
            )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != VERIFIER_CONTEXT_SCHEMA_VERSION:
            raise ProofVerifierError(
                f"unsupported verifier context schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "accept_simulated": self.accept_simulated,
            "approved_backends": list(self.approved_backends),
            "approved_proof_systems": list(self.approved_proof_systems),
            "at_time": self.at_time,
            "corpus_root_cid": self.corpus_root_cid,
            "expected_jurisdiction": self.expected_jurisdiction,
            "expected_tenant": self.expected_tenant,
            "require_complete_coverage": self.require_complete_coverage,
            "require_native_or_zk": self.require_native_or_zk,
            "revocation_root_cid": self.revocation_root_cid,
            "revoked_envelope_cids": list(self.revoked_envelope_cids),
            "schema_version": self.schema_version,
        }
        if self.trust_policy is not None:
            payload["trust_policy_digest"] = self.trust_policy.policy_digest()
            payload["trust_policy_id"] = self.trust_policy.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class SelectedEvidenceItem:
    """One selected evidence unit presented to the consumer verifier.

    Producer status and cache-hit flags are recorded only as adversarial claims
    — they never authorize.  Partial fetch and tenant claims are fail-closed
    signals.
    """

    envelope: AttestedProofEnvelope | Mapping[str, Any]
    native_proof_bytes: bytes | str | None = None
    zk_attestation: Mapping[str, Any] | None = None
    body_bytes: bytes | str | None = None
    parent_envelopes: tuple[AttestedProofEnvelope | Mapping[str, Any], ...] = ()
    item_id: str = ""
    producer_claim_status: str = ""
    cache_hit: bool = False
    fetch_complete: bool = True
    claimed_tenant: str = ""
    claimed_algorithm: str = ""
    previous_algorithm: str = ""
    real_to_simulation_fallback: bool = False
    schema_version: str = SELECTED_EVIDENCE_ITEM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        env = self.envelope
        if isinstance(env, AttestedProofEnvelope):
            env = env.verify_integrity()
        else:
            env = AttestedProofEnvelope.from_dict(
                _as_mapping(env, "envelope")
            ).verify_integrity()
        object.__setattr__(self, "envelope", env)

        native = self.native_proof_bytes
        if native is None or native == "":
            object.__setattr__(self, "native_proof_bytes", b"")
        else:
            object.__setattr__(
                self,
                "native_proof_bytes",
                _normalize_bytes(native, "native_proof_bytes"),
            )

        if self.zk_attestation in (None, {}):
            object.__setattr__(self, "zk_attestation", None)
        else:
            object.__setattr__(
                self,
                "zk_attestation",
                MappingProxyType(
                    _json_ready(
                        dict(_as_mapping(self.zk_attestation, "zk_attestation"))
                    )
                ),
            )

        body = self.body_bytes
        if body is None or body == "":
            object.__setattr__(self, "body_bytes", b"")
        else:
            object.__setattr__(
                self, "body_bytes", _normalize_bytes(body, "body_bytes")
            )

        parents: list[AttestedProofEnvelope] = []
        if self.parent_envelopes not in (None, ()):
            if isinstance(self.parent_envelopes, (str, bytes, bytearray, Mapping)):
                raise ProofVerifierError(
                    "parent_envelopes must be a sequence of envelopes"
                )
            try:
                for parent in self.parent_envelopes:
                    if isinstance(parent, AttestedProofEnvelope):
                        parents.append(parent.verify_integrity())
                    else:
                        parents.append(
                            AttestedProofEnvelope.from_dict(
                                _as_mapping(parent, "parent_envelope")
                            ).verify_integrity()
                        )
            except TypeError as exc:
                raise ProofVerifierError(
                    "parent_envelopes must be a sequence of envelopes"
                ) from exc
        object.__setattr__(self, "parent_envelopes", tuple(parents))

        object.__setattr__(
            self, "item_id", _optional_text(self.item_id, "item_id")
        )
        if not self.item_id:
            object.__setattr__(self, "item_id", env.envelope_cid)

        object.__setattr__(
            self,
            "producer_claim_status",
            _optional_text(
                self.producer_claim_status, "producer_claim_status"
            ),
        )
        if not isinstance(self.cache_hit, bool):
            raise ProofVerifierError("cache_hit must be a bool")
        if not isinstance(self.fetch_complete, bool):
            raise ProofVerifierError("fetch_complete must be a bool")
        if not isinstance(self.real_to_simulation_fallback, bool):
            raise ProofVerifierError(
                "real_to_simulation_fallback must be a bool"
            )
        object.__setattr__(
            self,
            "claimed_tenant",
            _optional_text(self.claimed_tenant, "claimed_tenant"),
        )
        object.__setattr__(
            self,
            "claimed_algorithm",
            _optional_text(self.claimed_algorithm, "claimed_algorithm"),
        )
        object.__setattr__(
            self,
            "previous_algorithm",
            _optional_text(self.previous_algorithm, "previous_algorithm"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != SELECTED_EVIDENCE_ITEM_SCHEMA_VERSION:
            raise ProofVerifierError(
                f"unsupported evidence item schema: {self.schema_version!r}"
            )

    @property
    def has_native_proof(self) -> bool:
        return bool(self.native_proof_bytes)

    @property
    def has_zk_attestation(self) -> bool:
        return self.zk_attestation is not None

    def evidence_kind(self) -> ProofEvidenceKind:
        if self.has_native_proof and self.has_zk_attestation:
            return ProofEvidenceKind.BOTH
        if self.has_native_proof:
            return ProofEvidenceKind.NATIVE
        if self.has_zk_attestation:
            return ProofEvidenceKind.ZK
        return ProofEvidenceKind.NONE

    def to_dict(self) -> dict[str, Any]:
        assert isinstance(self.envelope, AttestedProofEnvelope)
        native_hex = (
            bytes(self.native_proof_bytes).hex() if self.native_proof_bytes else ""
        )
        body_hex = bytes(self.body_bytes).hex() if self.body_bytes else ""
        return {
            "body_bytes": body_hex,
            "body_digest": (
                digest_of_bytes(self.body_bytes) if self.body_bytes else ""
            ),
            "cache_hit": self.cache_hit,
            "claimed_algorithm": self.claimed_algorithm,
            "claimed_tenant": self.claimed_tenant,
            "envelope": self.envelope.to_dict(),
            "envelope_cid": self.envelope.envelope_cid,
            "evidence_kind": self.evidence_kind().value,
            "fetch_complete": self.fetch_complete,
            "item_id": self.item_id,
            "native_proof_bytes": native_hex,
            "native_proof_digest": (
                digest_of_bytes(self.native_proof_bytes)
                if self.native_proof_bytes
                else ""
            ),
            "parent_cids": [
                parent.envelope_cid for parent in self.parent_envelopes
            ],
            "parent_envelopes": [
                parent.to_dict() for parent in self.parent_envelopes
            ],
            "previous_algorithm": self.previous_algorithm,
            "producer_claim_status": self.producer_claim_status,
            "real_to_simulation_fallback": self.real_to_simulation_fallback,
            "schema_version": self.schema_version,
            "zk_attestation": (
                dict(self.zk_attestation)
                if self.zk_attestation is not None
                else None
            ),
            "zk_attestation_present": self.has_zk_attestation,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "SelectedEvidenceItem":
        payload = dict(_as_mapping(value, "selected evidence item"))
        # Derived summary fields; ignore on load when present.
        for key in (
            "body_digest",
            "envelope_cid",
            "evidence_kind",
            "native_proof_digest",
            "parent_cids",
            "zk_attestation_present",
        ):
            payload.pop(key, None)
        _reject_unknown(
            payload,
            frozenset(
                {
                    "body_bytes",
                    "cache_hit",
                    "claimed_algorithm",
                    "claimed_tenant",
                    "envelope",
                    "fetch_complete",
                    "item_id",
                    "native_proof_bytes",
                    "parent_envelopes",
                    "previous_algorithm",
                    "producer_claim_status",
                    "real_to_simulation_fallback",
                    "schema_version",
                    "zk_attestation",
                }
            ),
            "selected evidence item",
        )
        return cls(
            envelope=payload.get("envelope", {}),
            native_proof_bytes=payload.get("native_proof_bytes"),
            zk_attestation=payload.get("zk_attestation"),
            body_bytes=payload.get("body_bytes"),
            parent_envelopes=tuple(payload.get("parent_envelopes", ()) or ()),
            item_id=payload.get("item_id", ""),
            producer_claim_status=payload.get("producer_claim_status", ""),
            cache_hit=bool(payload.get("cache_hit", False)),
            fetch_complete=bool(payload.get("fetch_complete", True)),
            claimed_tenant=payload.get("claimed_tenant", ""),
            claimed_algorithm=payload.get("claimed_algorithm", ""),
            previous_algorithm=payload.get("previous_algorithm", ""),
            real_to_simulation_fallback=bool(
                payload.get("real_to_simulation_fallback", False)
            ),
            schema_version=payload.get(
                "schema_version", SELECTED_EVIDENCE_ITEM_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ItemVerificationResult:
    """Per-item consumer verification outcome."""

    item_id: str
    envelope_cid: str
    status: VerificationStatus
    reasons: tuple[str, ...] = ()
    absent_bindings: tuple[str, ...] = ()
    grants_authority: bool = False
    evidence_kind: str = ProofEvidenceKind.NONE.value
    schema_version: str = ITEM_VERIFICATION_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "item_id", _require_text(self.item_id, "item_id")
        )
        object.__setattr__(
            self,
            "envelope_cid",
            _require_cid(self.envelope_cid, "envelope_cid"),
        )
        object.__setattr__(
            self,
            "status",
            _parse_enum(self.status, VerificationStatus, "status"),
        )
        object.__setattr__(
            self, "reasons", _unique_texts(self.reasons, "reasons")
        )
        object.__setattr__(
            self,
            "absent_bindings",
            _unique_texts(self.absent_bindings, "absent_bindings"),
        )
        if not isinstance(self.grants_authority, bool):
            raise ProofVerifierError("grants_authority must be a bool")
        # Fail closed: reject/fail never grant authority.
        if self.status is not VerificationStatus.PASS and self.grants_authority:
            raise ProofVerifierError(
                "grants_authority requires status=pass"
            )
        object.__setattr__(
            self,
            "evidence_kind",
            _optional_text(self.evidence_kind, "evidence_kind")
            or ProofEvidenceKind.NONE.value,
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != ITEM_VERIFICATION_RESULT_SCHEMA_VERSION:
            raise ProofVerifierError(
                f"unsupported item result schema: {self.schema_version!r}"
            )

    @property
    def passed(self) -> bool:
        return self.status is VerificationStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "absent_bindings": list(self.absent_bindings),
            "envelope_cid": self.envelope_cid,
            "evidence_kind": self.evidence_kind,
            "grants_authority": self.grants_authority,
            "item_id": self.item_id,
            "reasons": list(self.reasons),
            "schema_version": self.schema_version,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ItemVerificationResult":
        payload = dict(_as_mapping(value, "item verification result"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "absent_bindings",
                    "envelope_cid",
                    "evidence_kind",
                    "grants_authority",
                    "item_id",
                    "reasons",
                    "schema_version",
                    "status",
                }
            ),
            "item verification result",
        )
        return cls(
            item_id=payload.get("item_id", ""),
            envelope_cid=payload.get("envelope_cid", ""),
            status=payload.get("status", VerificationStatus.FAIL.value),
            reasons=tuple(payload.get("reasons", ()) or ()),
            absent_bindings=tuple(payload.get("absent_bindings", ()) or ()),
            grants_authority=bool(payload.get("grants_authority", False)),
            evidence_kind=payload.get(
                "evidence_kind", ProofEvidenceKind.NONE.value
            ),
            schema_version=payload.get(
                "schema_version", ITEM_VERIFICATION_RESULT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ConsumerVerificationReceipt:
    """Content-addressed consumer receipt for a selected evidence pack.

    Authority is granted only when every item independently passes.  The
    receipt never elevates producer claims, cache hits, or incomplete legacy
    material.
    """

    status: VerificationStatus
    item_results: tuple[ItemVerificationResult, ...] = ()
    grants_authority: bool = False
    corpus_root_cid: str = ""
    revocation_root_cid: str = ""
    context_digest: str = ""
    pack_digest: str = ""
    reasons: tuple[str, ...] = ()
    content_digest: str = ""
    content_cid: str = ""
    schema_version: str = CONSUMER_VERIFICATION_RECEIPT_SCHEMA_VERSION
    interface: str = ATTESTED_PROOF_VERIFIER_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _parse_enum(self.status, VerificationStatus, "status"),
        )
        results: list[ItemVerificationResult] = []
        if self.item_results not in (None, ()):
            if isinstance(
                self.item_results, (str, bytes, bytearray, Mapping)
            ):
                raise ProofVerifierError(
                    "item_results must be a sequence of ItemVerificationResult"
                )
            try:
                for item in self.item_results:
                    if isinstance(item, ItemVerificationResult):
                        results.append(item)
                    else:
                        results.append(ItemVerificationResult.from_dict(item))
            except TypeError as exc:
                raise ProofVerifierError(
                    "item_results must be a sequence of ItemVerificationResult"
                ) from exc
        object.__setattr__(self, "item_results", tuple(results))
        if not isinstance(self.grants_authority, bool):
            raise ProofVerifierError("grants_authority must be a bool")
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
        object.__setattr__(
            self,
            "context_digest",
            _optional_digest(self.context_digest, "context_digest"),
        )
        object.__setattr__(
            self, "pack_digest", _optional_digest(self.pack_digest, "pack_digest")
        )
        object.__setattr__(
            self, "reasons", _unique_texts(self.reasons, "reasons")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != CONSUMER_VERIFICATION_RECEIPT_SCHEMA_VERSION:
            raise ProofVerifierError(
                f"unsupported receipt schema: {self.schema_version!r}"
            )
        if self.interface != ATTESTED_PROOF_VERIFIER_INTERFACE:
            raise ProofVerifierError(
                f"unsupported receipt interface: {self.interface!r}"
            )

        # Fail-closed authority: only pass with all items granting.
        all_items_pass = bool(results) and all(
            item.grants_authority and item.passed for item in results
        )
        if self.status is VerificationStatus.PASS:
            if not all_items_pass or not self.grants_authority:
                raise ProofVerifierError(
                    "receipt status=pass requires every item to grant authority"
                )
        else:
            if self.grants_authority:
                raise ProofVerifierError(
                    "grants_authority is forbidden when status is not pass"
                )

        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest:
            recorded = _require_digest(self.content_digest, "content_digest")
            if recorded != digest:
                raise ProofVerifierIntegrityError(
                    "receipt content_digest does not match payload"
                )
        if self.content_cid:
            recorded_cid = _require_cid(self.content_cid, "content_cid")
            if recorded_cid != cid:
                raise ProofVerifierIntegrityError(
                    "receipt content_cid does not match payload"
                )
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "context_digest": self.context_digest,
            "corpus_root_cid": self.corpus_root_cid,
            "grants_authority": self.grants_authority,
            "interface": self.interface,
            "item_results": [item.to_dict() for item in self.item_results],
            "pack_digest": self.pack_digest,
            "reasons": list(self.reasons),
            "revocation_root_cid": self.revocation_root_cid,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        return payload

    def verify_integrity(self) -> "ConsumerVerificationReceipt":
        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if digest != self.content_digest or cid != self.content_cid:
            raise ProofVerifierIntegrityError(
                "receipt content identity does not match recomputed identity"
            )
        return self

    @classmethod
    def from_dict(cls, value: Any) -> "ConsumerVerificationReceipt":
        payload = dict(_as_mapping(value, "consumer verification receipt"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "content_cid",
                    "content_digest",
                    "context_digest",
                    "corpus_root_cid",
                    "grants_authority",
                    "interface",
                    "item_results",
                    "pack_digest",
                    "reasons",
                    "revocation_root_cid",
                    "schema_version",
                    "status",
                }
            ),
            "consumer verification receipt",
        )
        return cls(
            status=payload.get("status", VerificationStatus.FAIL.value),
            item_results=tuple(payload.get("item_results", ()) or ()),
            grants_authority=bool(payload.get("grants_authority", False)),
            corpus_root_cid=payload.get("corpus_root_cid", ""),
            revocation_root_cid=payload.get("revocation_root_cid", ""),
            context_digest=payload.get("context_digest", ""),
            pack_digest=payload.get("pack_digest", ""),
            reasons=tuple(payload.get("reasons", ()) or ()),
            content_digest=payload.get("content_digest", ""),
            content_cid=payload.get("content_cid", ""),
            schema_version=payload.get(
                "schema_version", CONSUMER_VERIFICATION_RECEIPT_SCHEMA_VERSION
            ),
            interface=payload.get(
                "interface", ATTESTED_PROOF_VERIFIER_INTERFACE
            ),
        )


# ---------------------------------------------------------------------------
# SelectedEvidencePack
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SelectedEvidencePack:
    """Selected evidence pack with optional consumer verification receipt."""

    items: tuple[SelectedEvidenceItem | Mapping[str, Any], ...]
    context: VerifierContext | Mapping[str, Any]
    receipt: ConsumerVerificationReceipt | Mapping[str, Any] | None = None
    pack_id: str = ""
    content_digest: str = ""
    content_cid: str = ""
    schema_version: str = SELECTED_EVIDENCE_PACK_SCHEMA_VERSION
    interface: str = SELECTED_EVIDENCE_PACK_INTERFACE

    def __post_init__(self) -> None:
        ctx = self.context
        if not isinstance(ctx, VerifierContext):
            ctx_payload = dict(_as_mapping(ctx, "context"))
            # trust_policy is not rehydrated from digest-only wire form here.
            ctx_payload.pop("trust_policy_digest", None)
            ctx_payload.pop("trust_policy_id", None)
            ctx = VerifierContext(
                corpus_root_cid=ctx_payload.get("corpus_root_cid", ""),
                revocation_root_cid=ctx_payload.get("revocation_root_cid", ""),
                expected_tenant=ctx_payload.get("expected_tenant", ""),
                expected_jurisdiction=ctx_payload.get(
                    "expected_jurisdiction", ""
                ),
                at_time=ctx_payload.get("at_time", ""),
                approved_proof_systems=tuple(
                    ctx_payload.get("approved_proof_systems")
                    or sorted(DEFAULT_APPROVED_PROOF_SYSTEMS)
                ),
                approved_backends=tuple(
                    ctx_payload.get("approved_backends")
                    or sorted(DEFAULT_APPROVED_BACKENDS)
                ),
                revoked_envelope_cids=tuple(
                    ctx_payload.get("revoked_envelope_cids", ()) or ()
                ),
                accept_simulated=bool(
                    ctx_payload.get("accept_simulated", False)
                ),
                require_native_or_zk=bool(
                    ctx_payload.get("require_native_or_zk", True)
                ),
                require_complete_coverage=bool(
                    ctx_payload.get("require_complete_coverage", True)
                ),
                schema_version=ctx_payload.get(
                    "schema_version", VERIFIER_CONTEXT_SCHEMA_VERSION
                ),
            )
        object.__setattr__(self, "context", ctx)

        items: list[SelectedEvidenceItem] = []
        if self.items in (None, ()):
            raise ProofVerifierError(
                "SelectedEvidencePack requires at least one item"
            )
        if isinstance(self.items, (str, bytes, bytearray, Mapping)):
            raise ProofVerifierError(
                "items must be a sequence of SelectedEvidenceItem"
            )
        try:
            for item in self.items:
                if isinstance(item, SelectedEvidenceItem):
                    items.append(item)
                else:
                    items.append(SelectedEvidenceItem.from_dict(item))
        except TypeError as exc:
            raise ProofVerifierError(
                "items must be a sequence of SelectedEvidenceItem"
            ) from exc
        object.__setattr__(self, "items", tuple(items))

        receipt = self.receipt
        if receipt in (None, {}):
            object.__setattr__(self, "receipt", None)
        elif isinstance(receipt, ConsumerVerificationReceipt):
            object.__setattr__(self, "receipt", receipt.verify_integrity())
        else:
            object.__setattr__(
                self,
                "receipt",
                ConsumerVerificationReceipt.from_dict(
                    _as_mapping(receipt, "receipt")
                ).verify_integrity(),
            )

        object.__setattr__(
            self, "pack_id", _optional_text(self.pack_id, "pack_id")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != SELECTED_EVIDENCE_PACK_SCHEMA_VERSION:
            raise ProofVerifierError(
                f"unsupported evidence pack schema: {self.schema_version!r}"
            )
        if self.interface != SELECTED_EVIDENCE_PACK_INTERFACE:
            raise ProofVerifierError(
                f"unsupported evidence pack interface: {self.interface!r}"
            )

        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if self.content_digest:
            recorded = _require_digest(self.content_digest, "content_digest")
            if recorded != digest:
                raise ProofVerifierIntegrityError(
                    "pack content_digest does not match payload"
                )
        if self.content_cid:
            recorded_cid = _require_cid(self.content_cid, "content_cid")
            if recorded_cid != cid:
                raise ProofVerifierIntegrityError(
                    "pack content_cid does not match payload"
                )
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(self, "content_cid", cid)
        if not self.pack_id:
            object.__setattr__(self, "pack_id", cid)

    def _identity_payload(self) -> dict[str, Any]:
        assert isinstance(self.context, VerifierContext)
        # pack_id is an alias for content_cid when omitted; it is not part of
        # the content-addressed identity (avoids chicken-and-egg assignment).
        return {
            "context": self.context.to_dict(),
            "interface": self.interface,
            "items": [item.to_dict() for item in self.items],
            "receipt": (
                self.receipt.to_dict() if self.receipt is not None else None
            ),
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_cid"] = self.content_cid
        payload["content_digest"] = self.content_digest
        payload["pack_id"] = self.pack_id
        return payload

    def verify_integrity(self) -> "SelectedEvidencePack":
        body = self._identity_payload()
        digest = _sha256_digest(_canonical_bytes(body))
        cid = cid_v1_from_digest(bytes.fromhex(digest.removeprefix("sha256:")))
        if digest != self.content_digest or cid != self.content_cid:
            raise ProofVerifierIntegrityError(
                "pack content identity does not match recomputed identity"
            )
        return self

    def with_receipt(
        self, receipt: ConsumerVerificationReceipt
    ) -> "SelectedEvidencePack":
        """Return a new pack bound to *receipt* (identity rehashed)."""

        return SelectedEvidencePack(
            items=self.items,
            context=self.context,
            receipt=receipt,
            pack_id=self.pack_id,
            schema_version=self.schema_version,
            interface=self.interface,
        )

    @classmethod
    def from_dict(cls, value: Any) -> "SelectedEvidencePack":
        payload = dict(_as_mapping(value, "selected evidence pack"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "content_cid",
                    "content_digest",
                    "context",
                    "interface",
                    "items",
                    "pack_id",
                    "receipt",
                    "schema_version",
                }
            ),
            "selected evidence pack",
        )
        return cls(
            items=tuple(payload.get("items", ()) or ()),
            context=payload.get("context", {}),
            receipt=payload.get("receipt"),
            pack_id=payload.get("pack_id", ""),
            content_digest=payload.get("content_digest", ""),
            content_cid=payload.get("content_cid", ""),
            schema_version=payload.get(
                "schema_version", SELECTED_EVIDENCE_PACK_SCHEMA_VERSION
            ),
            interface=payload.get(
                "interface", SELECTED_EVIDENCE_PACK_INTERFACE
            ),
        )


# ---------------------------------------------------------------------------
# Verifier implementation
# ---------------------------------------------------------------------------


def _zk_attestation_is_simulated(attestation: Mapping[str, Any]) -> bool:
    meta = attestation.get("metadata")
    if isinstance(meta, Mapping):
        if meta.get("is_simulated") is True:
            return True
        backend = str(meta.get("backend") or "").lower()
        if _algorithm_is_simulated(backend):
            return True
    if attestation.get("is_simulated") is True:
        return True
    backend = str(attestation.get("backend") or "").lower()
    if _algorithm_is_simulated(backend):
        return True
    return False


def _verify_native_proof(
    item: SelectedEvidenceItem,
    envelope: AttestedProofEnvelope,
    reasons: list[str],
) -> None:
    """Check native proof bytes bind the envelope digest (fail closed)."""

    proof_bytes = item.native_proof_bytes
    if not proof_bytes:
        return
    if not isinstance(proof_bytes, (bytes, bytearray)) or not proof_bytes:
        reasons.append(REASON_MALFORMED_PROOF)
        return
    # Empty or trivially short payloads are underconstrained.
    if len(proof_bytes) < 8:
        reasons.append(REASON_UNDERCONSTRAINED)
    expected = envelope.proof_bytes_digest
    if not expected:
        reasons.append(f"{REASON_MISSING_BINDING}:proof_bytes_digest")
        return
    actual = digest_of_bytes(bytes(proof_bytes))
    if actual != expected:
        reasons.append(REASON_FORGED_PROOF)
        reasons.append(REASON_NATIVE_DIGEST)
    # Structural markers: reject explicit underconstrained / forged labels.
    try:
        text = bytes(proof_bytes).decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    lowered = text.lower()
    if "underconstrained" in lowered:
        reasons.append(REASON_UNDERCONSTRAINED)
    if "forged" in lowered or "tampered" in lowered:
        reasons.append(REASON_FORGED_PROOF)
    if "malformed" in lowered:
        reasons.append(REASON_MALFORMED_PROOF)


def _verify_zk_attestation(
    item: SelectedEvidenceItem,
    envelope: AttestedProofEnvelope,
    context: VerifierContext,
    reasons: list[str],
) -> None:
    """Check optional ZK attestation structure and simulation policy."""

    att = item.zk_attestation
    if att is None:
        return
    if not isinstance(att, Mapping) or not att:
        reasons.append(REASON_MALFORMED_PROOF)
        return
    # Simulated path rejection unless explicitly accepted (never production).
    if _zk_attestation_is_simulated(att):
        if not context.accept_simulated:
            reasons.append(REASON_ZK_SIMULATED)
        # Even when accepted for tests, simulation never authorizes theorem.
        if envelope.result_authority is AuthorityKind.THEOREM_PROOF:
            if envelope.attestation_kind is AttestationKind.DIRECT_PROOF_VERIFICATION:
                # Real direct-verification claim with simulated ZK is fallback.
                reasons.append(REASON_REAL_TO_SIM)
    # Public-input binding when present on attestation.
    att_inputs = att.get("public_inputs")
    if isinstance(att_inputs, Mapping) and att_inputs:
        expected = dict(envelope.public_inputs) or dict(
            envelope.circuit.public_inputs
        )
        if expected and dict(att_inputs) != expected:
            reasons.append(REASON_PUBLIC_INPUTS)
    # Statement digest binding when present.
    att_statement = (
        att.get("statement_digest")
        or (att.get("statement") or {}).get("statement_digest")
        if isinstance(att.get("statement"), Mapping)
        else att.get("statement_digest")
    )
    if isinstance(att.get("statement"), Mapping):
        stmt = att["statement"]
        att_statement = (
            stmt.get("statement_digest")
            or stmt.get("constraint_digest")
            or att_statement
        )
    if att_statement and str(att_statement) not in (
        envelope.statement_digest,
        envelope.public_inputs.get("statement_digest", ""),
    ):
        # Soft bind: only flag when both sides present and disagree.
        reasons.append(REASON_ZK_FAILED)
    # Explicit failure markers.
    if att.get("valid") is False or att.get("verified") is False:
        reasons.append(REASON_ZK_FAILED)
    if att.get("malformed") is True or att.get("forged") is True:
        reasons.append(REASON_FORGED_PROOF)
    if att.get("underconstrained") is True:
        reasons.append(REASON_UNDERCONSTRAINED)


def _check_algorithms(
    item: SelectedEvidenceItem,
    envelope: AttestedProofEnvelope,
    context: VerifierContext,
    reasons: list[str],
) -> None:
    circuit = envelope.circuit
    assert isinstance(circuit, CircuitBinding)
    proof_system = (
        item.claimed_algorithm
        or circuit.proof_system
        or envelope.backend_id
        or ""
    )
    backend = envelope.backend_id or circuit.backend_id or ""

    if proof_system:
        if _algorithm_is_simulated(proof_system) and not context.accept_simulated:
            reasons.append(REASON_REAL_TO_SIM)
        if context.approved_proof_systems and proof_system not in (
            context.approved_proof_systems
        ):
            # Backend-only labels may still be approved via backends.
            if proof_system not in context.approved_backends:
                reasons.append(REASON_UNKNOWN_ALGORITHM)
    elif context.require_native_or_zk:
        # Algorithm identity required for authoritative path.
        if not backend:
            reasons.append(REASON_UNKNOWN_ALGORITHM)

    if backend:
        if _algorithm_is_simulated(backend) and not context.accept_simulated:
            reasons.append(REASON_UNKNOWN_BACKEND)
        if (
            context.approved_backends
            and backend not in context.approved_backends
            and not _algorithm_is_simulated(backend)
        ):
            reasons.append(REASON_UNKNOWN_BACKEND)

    # Downgrade: previous stronger algorithm replaced by weaker/simulated.
    if item.previous_algorithm and proof_system:
        prev = item.previous_algorithm
        if prev != proof_system:
            if _algorithm_is_simulated(proof_system) and not _algorithm_is_simulated(
                prev
            ):
                reasons.append(REASON_ALGORITHM_DOWNGRADED)
                reasons.append(REASON_REAL_TO_SIM)
            elif (
                prev in context.approved_proof_systems
                and proof_system not in context.approved_proof_systems
            ):
                reasons.append(REASON_ALGORITHM_DOWNGRADED)

    if item.real_to_simulation_fallback:
        reasons.append(REASON_REAL_TO_SIM)


def _check_scope_roots_time(
    envelope: AttestedProofEnvelope,
    context: VerifierContext,
    item: SelectedEvidenceItem,
    reasons: list[str],
) -> None:
    if envelope.corpus_root_cid != context.corpus_root_cid:
        reasons.append(REASON_ROOT_MISMATCH)
        reasons.append(f"{REASON_ROOT_MISMATCH}:corpus")
    if context.revocation_root_cid:
        if not envelope.revocation_root_cid:
            reasons.append(f"{REASON_MISSING_BINDING}:revocation_root_cid")
        elif envelope.revocation_root_cid != context.revocation_root_cid:
            reasons.append(REASON_ROOT_MISMATCH)
            reasons.append(f"{REASON_ROOT_MISMATCH}:revocation")

    scope = envelope.scope
    assert isinstance(scope, ScopeBinding)
    if context.expected_tenant:
        if not scope.tenant:
            reasons.append(f"{REASON_MISSING_BINDING}:scope.tenant")
        elif scope.tenant != context.expected_tenant:
            reasons.append(REASON_CROSS_TENANT)
    if item.claimed_tenant and scope.tenant:
        if item.claimed_tenant != scope.tenant:
            reasons.append(REASON_CROSS_TENANT)
    if context.expected_jurisdiction:
        if not scope.jurisdiction:
            reasons.append(f"{REASON_MISSING_BINDING}:scope.jurisdiction")
        elif scope.jurisdiction != context.expected_jurisdiction:
            reasons.append(REASON_CROSS_TENANT)

    if envelope.is_revoked():
        reasons.append(REASON_REVOKED)
    if envelope.envelope_cid in context.revoked_envelope_cids:
        reasons.append(REASON_REVOKED)
    if envelope.is_superseded():
        reasons.append(REASON_SUPERSEDED)
    if context.at_time:
        temporal = envelope.temporal
        assert isinstance(temporal, TemporalWindow)
        if not temporal.is_effective_at(context.at_time):
            reasons.append(REASON_EXPIRED)


def _check_circuit_public_inputs(
    envelope: AttestedProofEnvelope,
    reasons: list[str],
) -> None:
    circuit = envelope.circuit
    assert isinstance(circuit, CircuitBinding)
    if not circuit.circuit_id or not circuit.circuit_digest:
        reasons.append(REASON_CIRCUIT_VK)
    if not circuit.vk_id and not circuit.vk_digest:
        reasons.append(REASON_CIRCUIT_VK)
    public_inputs = dict(envelope.public_inputs) or dict(circuit.public_inputs)
    if not public_inputs:
        reasons.append(REASON_UNDERCONSTRAINED)
        reasons.append(REASON_PUBLIC_INPUTS)
    else:
        # Statement digest must appear when theorem authority is claimed.
        if envelope.result_authority is AuthorityKind.THEOREM_PROOF:
            stmt = public_inputs.get("statement_digest")
            if not stmt:
                reasons.append(REASON_UNDERCONSTRAINED)
            elif stmt != envelope.statement_digest:
                reasons.append(REASON_PUBLIC_INPUTS)
        # Circuit public inputs must agree with top-level when both set.
        circuit_inputs = dict(circuit.public_inputs)
        top_inputs = dict(envelope.public_inputs)
        if circuit_inputs and top_inputs and circuit_inputs != top_inputs:
            reasons.append(REASON_PUBLIC_INPUTS)


def _check_parents(
    item: SelectedEvidenceItem,
    envelope: AttestedProofEnvelope,
    reasons: list[str],
) -> None:
    expected = set(envelope.parent_cids)
    if not expected:
        # Binding present but empty is still reported as missing for authority.
        reasons.append(f"{REASON_MISSING_BINDING}:parent_cids")
        return
    provided = {parent.envelope_cid for parent in item.parent_envelopes}
    if not item.parent_envelopes:
        reasons.append(REASON_PARENT_MISSING)
        return
    if not expected.issubset(provided):
        reasons.append(REASON_PARENT_MISMATCH)
    for parent in item.parent_envelopes:
        try:
            parent.verify_integrity()
        except AttestedProofIntegrityError:
            reasons.append(REASON_PARENT_MISMATCH)


def _check_coverage(
    envelope: AttestedProofEnvelope,
    context: VerifierContext,
    reasons: list[str],
) -> None:
    coverage = envelope.coverage
    assert isinstance(coverage, CoverageDeclaration)
    if context.require_complete_coverage:
        if not coverage.complete:
            reasons.append(REASON_COVERAGE_INCOMPLETE)
        if coverage.gap_kinds:
            reasons.append(REASON_COVERAGE_INCOMPLETE)
    if not coverage.covered_selectors and not coverage.complete:
        reasons.append(f"{REASON_MISSING_BINDING}:coverage")


def verify_selected_item(
    item: SelectedEvidenceItem | Mapping[str, Any],
    context: VerifierContext,
) -> ItemVerificationResult:
    """Independently verify one selected evidence item (fail closed)."""

    if not isinstance(item, SelectedEvidenceItem):
        item = SelectedEvidenceItem.from_dict(item)
    if not isinstance(context, VerifierContext):
        raise ProofVerifierError("context must be a VerifierContext")

    envelope = item.envelope
    assert isinstance(envelope, AttestedProofEnvelope)
    reasons: list[str] = []

    try:
        envelope.verify_integrity()
    except AttestedProofIntegrityError:
        reasons.append(REASON_INTEGRITY)

    # Producer claims / cache hits never authorize (always recorded as reject).
    if item.producer_claim_status:
        # Non-empty producer status alone is not proof.
        if item.producer_claim_status.lower() in {
            "proved",
            "pass",
            "ok",
            "verified",
            "approved",
            "success",
        }:
            reasons.append(REASON_PRODUCER_CLAIM)
    if item.cache_hit:
        reasons.append(REASON_CACHE_HIT)
    if not item.fetch_complete:
        reasons.append(REASON_PARTIAL_FETCH)

    # Membership never becomes theorem.
    if envelope.attestation_kind is AttestationKind.ARTIFACT_MEMBERSHIP:
        if envelope.result_authority is AuthorityKind.THEOREM_PROOF:
            reasons.append(REASON_MEMBERSHIP_THEOREM)
        else:
            reasons.append(REASON_MEMBERSHIP_THEOREM)
    if envelope.attestation_kind is AttestationKind.SIMULATION:
        reasons.append(REASON_SIMULATION_AUTHORITY)
        if not context.accept_simulated:
            reasons.append(REASON_REAL_TO_SIM)

    absent = absent_authority_bindings(envelope)
    for binding in absent:
        reasons.append(f"{REASON_MISSING_BINDING}:{binding}")

    _check_scope_roots_time(envelope, context, item, reasons)
    _check_circuit_public_inputs(envelope, reasons)
    _check_algorithms(item, envelope, context, reasons)
    _check_coverage(envelope, context, reasons)
    _check_parents(item, envelope, reasons)

    evidence_kind = item.evidence_kind()
    if context.require_native_or_zk and evidence_kind is ProofEvidenceKind.NONE:
        # Direct verification / verifier-execution require material.
        if envelope.attestation_kind in (
            AttestationKind.DIRECT_PROOF_VERIFICATION,
            AttestationKind.VERIFIER_EXECUTION,
        ):
            reasons.append(REASON_MISSING_PROOF)

    _verify_native_proof(item, envelope, reasons)
    _verify_zk_attestation(item, envelope, context, reasons)

    if context.trust_policy is not None:
        evaluation = context.trust_policy.evaluate(
            envelope, at_time=context.at_time, raise_on_reject=False
        )
        if evaluation.status is not TrustEvaluationStatus.ACCEPT:
            reasons.append(REASON_TRUST_POLICY)
            for policy_reason in evaluation.reasons:
                reasons.append(f"{REASON_TRUST_POLICY}:{policy_reason}")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            ordered.append(reason)

    if ordered:
        # Classify hard integrity failures as FAIL; policy/claim rejections as REJECT.
        hard_tokens = (
            REASON_INTEGRITY,
            REASON_FORGED_PROOF,
            REASON_MALFORMED_PROOF,
            REASON_NATIVE_DIGEST,
            REASON_ZK_FAILED,
        )
        status = (
            VerificationStatus.FAIL
            if any(token in ordered for token in hard_tokens)
            else VerificationStatus.REJECT
        )
        return ItemVerificationResult(
            item_id=item.item_id,
            envelope_cid=envelope.envelope_cid,
            status=status,
            reasons=tuple(ordered),
            absent_bindings=absent,
            grants_authority=False,
            evidence_kind=evidence_kind.value,
        )

    # Pass only when theorem-authoritative direct verification path is sound.
    grants = (
        attestation_kind_is_theorem_authoritative(envelope.attestation_kind)
        and envelope.result_authority is AuthorityKind.THEOREM_PROOF
        and evidence_kind is not ProofEvidenceKind.NONE
    )
    if not grants:
        # Verifier-execution may pass structural checks but does not grant
        # theorem authority unless policy elevated it — still report pass
        # without authority when structurally sound and non-theorem.
        return ItemVerificationResult(
            item_id=item.item_id,
            envelope_cid=envelope.envelope_cid,
            status=VerificationStatus.PASS,
            reasons=(),
            absent_bindings=(),
            grants_authority=False,
            evidence_kind=evidence_kind.value,
        )

    return ItemVerificationResult(
        item_id=item.item_id,
        envelope_cid=envelope.envelope_cid,
        status=VerificationStatus.PASS,
        reasons=(),
        absent_bindings=(),
        grants_authority=True,
        evidence_kind=evidence_kind.value,
    )


@dataclass(frozen=True, slots=True)
class AttestedProofVerifier:
    """Consumer-side independent proof verifier (AttestedProofVerifier@1)."""

    context: VerifierContext
    schema_version: str = ATTESTED_PROOF_VERIFIER_SCHEMA_VERSION
    interface: str = ATTESTED_PROOF_VERIFIER_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.context, VerifierContext):
            raise ProofVerifierError("context must be a VerifierContext")
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != ATTESTED_PROOF_VERIFIER_SCHEMA_VERSION:
            raise ProofVerifierError(
                f"unsupported verifier schema: {self.schema_version!r}"
            )
        if self.interface != ATTESTED_PROOF_VERIFIER_INTERFACE:
            raise ProofVerifierError(
                f"unsupported verifier interface: {self.interface!r}"
            )

    def verify_item(
        self, item: SelectedEvidenceItem | Mapping[str, Any]
    ) -> ItemVerificationResult:
        return verify_selected_item(item, self.context)

    def verify_pack(
        self, pack: SelectedEvidencePack | Mapping[str, Any]
    ) -> tuple[SelectedEvidencePack, ConsumerVerificationReceipt]:
        """Verify every item in *pack* and bind a consumer receipt."""

        if not isinstance(pack, SelectedEvidencePack):
            pack = SelectedEvidencePack.from_dict(pack)
        pack.verify_integrity()

        # Pack context roots must match verifier context (exact).
        pack_ctx = pack.context
        assert isinstance(pack_ctx, VerifierContext)
        if pack_ctx.corpus_root_cid != self.context.corpus_root_cid:
            raise ProofVerifierError(
                "pack corpus_root_cid does not match verifier context"
            )
        if (
            self.context.revocation_root_cid
            and pack_ctx.revocation_root_cid
            and pack_ctx.revocation_root_cid != self.context.revocation_root_cid
        ):
            raise ProofVerifierError(
                "pack revocation_root_cid does not match verifier context"
            )

        item_results = tuple(
            self.verify_item(item) for item in pack.items
        )
        all_grant = bool(item_results) and all(
            result.grants_authority and result.passed for result in item_results
        )
        pack_reasons: list[str] = []
        for result in item_results:
            if not result.passed:
                pack_reasons.extend(result.reasons)
        # Dedup
        seen: set[str] = set()
        ordered: list[str] = []
        for reason in pack_reasons:
            if reason not in seen:
                seen.add(reason)
                ordered.append(reason)

        if all_grant:
            status = VerificationStatus.PASS
            grants = True
        else:
            status = VerificationStatus.REJECT
            grants = False
            if any(r.status is VerificationStatus.FAIL for r in item_results):
                status = VerificationStatus.FAIL

        context_digest = _sha256_digest(
            _canonical_bytes(self.context.to_dict())
        )
        receipt = ConsumerVerificationReceipt(
            status=status,
            item_results=item_results,
            grants_authority=grants,
            corpus_root_cid=self.context.corpus_root_cid,
            revocation_root_cid=self.context.revocation_root_cid,
            context_digest=context_digest,
            pack_digest=pack.content_digest,
            reasons=tuple(ordered),
        )
        bound = pack.with_receipt(receipt)
        return bound, receipt

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "interface": self.interface,
            "schema_version": self.schema_version,
        }


def build_verifier_context(**kwargs: Any) -> VerifierContext:
    """Keyword sugar for :class:`VerifierContext`."""

    return VerifierContext(**kwargs)


def build_selected_evidence_item(**kwargs: Any) -> SelectedEvidenceItem:
    """Keyword sugar for :class:`SelectedEvidenceItem`."""

    return SelectedEvidenceItem(**kwargs)


def build_selected_evidence_pack(**kwargs: Any) -> SelectedEvidencePack:
    """Keyword sugar for :class:`SelectedEvidencePack`."""

    return SelectedEvidencePack(**kwargs)


def build_attested_proof_verifier(
    context: VerifierContext | None = None, **context_kwargs: Any
) -> AttestedProofVerifier:
    """Build an :class:`AttestedProofVerifier` from context or kwargs."""

    if context is None:
        context = VerifierContext(**context_kwargs)
    elif context_kwargs:
        raise ProofVerifierError(
            "pass either context or context kwargs, not both"
        )
    return AttestedProofVerifier(context=context)


__all__ = [
    "ATTESTED_PROOF_VERIFIER_INTERFACE",
    "ATTESTED_PROOF_VERIFIER_SCHEMA_VERSION",
    "CONSUMER_VERIFICATION_RECEIPT_SCHEMA_VERSION",
    "DEFAULT_APPROVED_BACKENDS",
    "DEFAULT_APPROVED_PROOF_SYSTEMS",
    "ITEM_VERIFICATION_RESULT_SCHEMA_VERSION",
    "REASON_ALGORITHM_DOWNGRADED",
    "REASON_CACHE_HIT",
    "REASON_CROSS_TENANT",
    "REASON_FORGED_PROOF",
    "REASON_MALFORMED_PROOF",
    "REASON_MEMBERSHIP_THEOREM",
    "REASON_MISSING_PROOF",
    "REASON_PARTIAL_FETCH",
    "REASON_PRODUCER_CLAIM",
    "REASON_REAL_TO_SIM",
    "REASON_UNDERCONSTRAINED",
    "REASON_UNKNOWN_ALGORITHM",
    "REQUIRED_AUTHORITY_BINDINGS",
    "SELECTED_EVIDENCE_ITEM_SCHEMA_VERSION",
    "SELECTED_EVIDENCE_PACK_INTERFACE",
    "SELECTED_EVIDENCE_PACK_SCHEMA_VERSION",
    "VERIFIER_CONTEXT_SCHEMA_VERSION",
    "AttestedProofVerifier",
    "ConsumerVerificationReceipt",
    "ItemVerificationResult",
    "ProofEvidenceKind",
    "ProofVerifierError",
    "ProofVerifierIntegrityError",
    "SelectedEvidenceItem",
    "SelectedEvidencePack",
    "VerificationStatus",
    "VerifierContext",
    "absent_authority_bindings",
    "binding_value",
    "build_attested_proof_verifier",
    "build_selected_evidence_item",
    "build_selected_evidence_pack",
    "build_verifier_context",
    "digest_of_bytes",
    "is_binding_present",
    "verify_selected_item",
]
