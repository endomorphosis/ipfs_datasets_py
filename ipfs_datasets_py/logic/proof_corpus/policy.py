"""Trust and coverage policy for authority-grade proof envelopes (LIG-029).

Interfaces:

* ``ProofTrustPolicy@1`` — exact roots, allowlists, minimums, budgets,
  open/closed-world evaluation, and conflict rules that govern whether an
  :class:`~.model.AttestedProofEnvelope` may be treated as authorization
  evidence.
* ``CorpusCoveragePolicy@1`` — required domains, selectors, and completeness
  thresholds for corpus coverage before ranking or allow.

Non-substitutability (acceptance / plan §6.3 / §10.3):

* direct proof verification, verifier execution, artifact membership,
  signature evidence, and simulation are distinct evidence classes;
* membership, signature, and simulation never become theorem authority;
* verifier execution never silently upgrades to direct verification;
* policy mutations that would permit a forbidden substitution fail closed.

This leaf owns policy identity and evaluation only.  Manifest, revocation,
query, and independent verification leave live in later LIG tasks.
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

from ..ir_core.protocols import AuthorityKind
from .model import (
    NON_SUBSTITUTABLE_EVIDENCE_KINDS,
    AttestationKind,
    AttestedProofEnvelope,
    AttestedProofModelError,
    CoverageDeclaration,
    parse_attestation_kind,
    parse_result_authority,
)

PROOF_TRUST_POLICY_INTERFACE: Final = "ProofTrustPolicy@1"
PROOF_TRUST_POLICY_SCHEMA_VERSION: Final = "proof-trust-policy/v1"
CORPUS_COVERAGE_POLICY_INTERFACE: Final = "CorpusCoveragePolicy@1"
CORPUS_COVERAGE_POLICY_SCHEMA_VERSION: Final = "corpus-coverage-policy/v1"
POLICY_BUDGET_SCHEMA_VERSION: Final = "proof-trust-budget/v1"
POLICY_EVALUATION_SCHEMA_VERSION: Final = "proof-trust-evaluation/v1"

_PROFILE_RE: Final = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_CID_RE: Final = re.compile(r"^b[a-z2-7]{10,200}$")

# Evidence classes that can never be allowlisted as theorem authority.
_FORBIDDEN_THEOREM_KINDS: Final[frozenset[str]] = frozenset(
    {
        AttestationKind.ARTIFACT_MEMBERSHIP.value,
        AttestationKind.SIMULATION.value,
        "signature",
    }
)

# Full non-substitutable closed set (acceptance criterion).
NON_SUBSTITUTABLE_POLICY_EVIDENCE: Final[frozenset[str]] = frozenset(
    {
        AttestationKind.DIRECT_PROOF_VERIFICATION.value,
        AttestationKind.VERIFIER_EXECUTION.value,
        AttestationKind.ARTIFACT_MEMBERSHIP.value,
        "signature",
        AttestationKind.SIMULATION.value,
    }
)


class ProofTrustPolicyError(AttestedProofModelError):
    """Raised when a trust or coverage policy is malformed."""


class ProofTrustPolicyViolation(ProofTrustPolicyError):
    """Raised when an envelope fails a trust-policy check."""


class WorldMode(str, Enum):
    """Open/closed-world evaluation policy for corpus queries."""

    CLOSED = "closed"
    OPEN = "open"


class ConflictRule(str, Enum):
    """How contradictory applicable authorities are resolved."""

    FAIL_CLOSED = "fail_closed"
    DENY_OVERRIDES = "deny_overrides"
    REVIEW = "review"
    INDETERMINATE = "indeterminate"


class TrustEvaluationStatus(str, Enum):
    """Outcome of evaluating an envelope under a trust policy."""

    ACCEPT = "accept"
    REJECT = "reject"
    ABSTAIN = "abstain"


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
    raise ProofTrustPolicyError(
        f"value of type {type(value).__name__} is not JSON-serializable "
        "for the trust policy"
    )


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProofTrustPolicyError(f"{label} must be a mapping")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProofTrustPolicyError(
            f"{field_name} must be a non-empty trimmed string"
        )
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, field_name)


def _require_cid(value: Any, field_name: str) -> str:
    cid = _require_text(value, field_name)
    if not _CID_RE.fullmatch(cid):
        raise ProofTrustPolicyError(
            f"{field_name} must be a CIDv1 base32 string"
        )
    return cid


def _optional_cid(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_cid(value, field_name)


def _require_profile(value: Any, field_name: str) -> str:
    profile = _require_text(value, field_name)
    if not _PROFILE_RE.fullmatch(profile):
        raise ProofTrustPolicyError(
            f"{field_name} must be a lowercase hyphenated identifier"
        )
    return profile


def _optional_profile(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_profile(value, field_name)


def _unique_texts(values: Any, field_name: str) -> tuple[str, ...]:
    if values in (None, ()):
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise ProofTrustPolicyError(
            f"{field_name} must be a sequence of strings"
        )
    try:
        items = tuple(_require_text(item, field_name) for item in values)
    except TypeError as exc:
        raise ProofTrustPolicyError(
            f"{field_name} must be a sequence of strings"
        ) from exc
    if len(items) != len(set(items)):
        raise ProofTrustPolicyError(f"{field_name} values must be unique")
    return items


def _unique_cids(values: Any, field_name: str) -> tuple[str, ...]:
    if values in (None, ()):
        return ()
    if isinstance(values, (str, bytes, bytearray)):
        raise ProofTrustPolicyError(f"{field_name} must be a sequence of CIDs")
    try:
        items = tuple(_require_cid(item, field_name) for item in values)
    except TypeError as exc:
        raise ProofTrustPolicyError(
            f"{field_name} must be a sequence of CIDs"
        ) from exc
    if len(items) != len(set(items)):
        raise ProofTrustPolicyError(f"{field_name} values must be unique")
    return items


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProofTrustPolicyError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _parse_enum(value: Any, enum_cls: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ProofTrustPolicyError(
            f"{field_name} must be one of: {allowed}"
        ) from exc


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProofTrustPolicyError(f"{field_name} must be a positive integer")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProofTrustPolicyError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def non_substitutable_evidence_kinds() -> frozenset[str]:
    """Return the closed set of non-substitutable evidence kinds."""

    # Keep model and policy vocabularies aligned.
    assert NON_SUBSTITUTABLE_POLICY_EVIDENCE == NON_SUBSTITUTABLE_EVIDENCE_KINDS
    return NON_SUBSTITUTABLE_POLICY_EVIDENCE


# ---------------------------------------------------------------------------
# Budgets / evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyBudget:
    """Finite resource budgets for trust-policy evaluation and query."""

    max_candidates: int = 256
    max_bytes: int = 8 * 1024 * 1024
    max_graph_depth: int = 32
    timeout_ms: int = 30_000
    max_backend_attempts: int = 8
    schema_version: str = POLICY_BUDGET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_candidates",
            _positive_int(self.max_candidates, "max_candidates"),
        )
        object.__setattr__(
            self, "max_bytes", _positive_int(self.max_bytes, "max_bytes")
        )
        object.__setattr__(
            self,
            "max_graph_depth",
            _positive_int(self.max_graph_depth, "max_graph_depth"),
        )
        object.__setattr__(
            self, "timeout_ms", _positive_int(self.timeout_ms, "timeout_ms")
        )
        object.__setattr__(
            self,
            "max_backend_attempts",
            _positive_int(self.max_backend_attempts, "max_backend_attempts"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != POLICY_BUDGET_SCHEMA_VERSION:
            raise ProofTrustPolicyError(
                f"unsupported policy budget schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_backend_attempts": self.max_backend_attempts,
            "max_bytes": self.max_bytes,
            "max_candidates": self.max_candidates,
            "max_graph_depth": self.max_graph_depth,
            "schema_version": self.schema_version,
            "timeout_ms": self.timeout_ms,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "PolicyBudget":
        if isinstance(value, PolicyBudget):
            return value
        payload = dict(_as_mapping(value, "budget"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "max_backend_attempts",
                    "max_bytes",
                    "max_candidates",
                    "max_graph_depth",
                    "schema_version",
                    "timeout_ms",
                }
            ),
            "policy budget",
        )
        return cls(
            max_candidates=int(payload.get("max_candidates", 256)),
            max_bytes=int(payload.get("max_bytes", 8 * 1024 * 1024)),
            max_graph_depth=int(payload.get("max_graph_depth", 32)),
            timeout_ms=int(payload.get("timeout_ms", 30_000)),
            max_backend_attempts=int(payload.get("max_backend_attempts", 8)),
            schema_version=payload.get(
                "schema_version", POLICY_BUDGET_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class TrustPolicyEvaluation:
    """Structured result of :meth:`ProofTrustPolicy.evaluate`."""

    status: TrustEvaluationStatus
    reasons: tuple[str, ...] = ()
    accepted_attestation_kind: str = ""
    required_result_authority: str = ""
    policy_digest: str = ""
    envelope_cid: str = ""
    schema_version: str = POLICY_EVALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _parse_enum(self.status, TrustEvaluationStatus, "status"),
        )
        object.__setattr__(
            self, "reasons", _unique_texts(self.reasons, "reasons")
        )
        object.__setattr__(
            self,
            "accepted_attestation_kind",
            _optional_text(
                self.accepted_attestation_kind, "accepted_attestation_kind"
            ),
        )
        object.__setattr__(
            self,
            "required_result_authority",
            _optional_text(
                self.required_result_authority, "required_result_authority"
            ),
        )
        object.__setattr__(
            self, "policy_digest", _optional_text(self.policy_digest, "policy_digest")
        )
        object.__setattr__(
            self, "envelope_cid", _optional_cid(self.envelope_cid, "envelope_cid")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != POLICY_EVALUATION_SCHEMA_VERSION:
            raise ProofTrustPolicyError(
                f"unsupported evaluation schema: {self.schema_version!r}"
            )

    @property
    def accepted(self) -> bool:
        return self.status is TrustEvaluationStatus.ACCEPT

    @property
    def rejected(self) -> bool:
        return self.status is TrustEvaluationStatus.REJECT

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_attestation_kind": self.accepted_attestation_kind,
            "envelope_cid": self.envelope_cid,
            "policy_digest": self.policy_digest,
            "reasons": list(self.reasons),
            "required_result_authority": self.required_result_authority,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }


# ---------------------------------------------------------------------------
# ProofTrustPolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofTrustPolicy:
    """Immutable trust policy for attested proof envelopes (ProofTrustPolicy@1).

    Declares exact corpus/revocation/policy/VK roots, allowlists for circuits,
    backends, attestation kinds, solvers, compilers, and security profiles,
    minimum authority/security requirements, resource budgets, open/closed-world
    mode, and conflict rules.  Non-substitutable evidence classes cannot be
    reclassified by allowlist mutation.
    """

    policy_id: str
    corpus_roots: tuple[str, ...] = ()
    revocation_roots: tuple[str, ...] = ()
    policy_roots: tuple[str, ...] = ()
    vk_registry_roots: tuple[str, ...] = ()
    circuit_allowlist: tuple[str, ...] = ()
    backend_allowlist: tuple[str, ...] = ()
    solver_allowlist: tuple[str, ...] = ()
    compiler_allowlist: tuple[str, ...] = ()
    security_profile_allowlist: tuple[str, ...] = ()
    attestation_kind_allowlist: tuple[str, ...] = (
        AttestationKind.DIRECT_PROOF_VERIFICATION.value,
    )
    # Verifier-execution may be admitted only when explicitly listed; never
    # membership/simulation/signature as theorem authority.
    authoritative_attestation_kinds: tuple[str, ...] = (
        AttestationKind.DIRECT_PROOF_VERIFICATION.value,
    )
    required_result_authority: AuthorityKind | str = AuthorityKind.THEOREM_PROOF
    minimum_security_profile: str = ""
    accept_simulated: bool = False
    accept_membership_as_theorem: bool = False
    accept_signature_as_theorem: bool = False
    require_circuit_binding: bool = True
    require_vk_binding: bool = True
    require_public_inputs: bool = True
    world_mode: WorldMode | str = WorldMode.CLOSED
    conflict_rule: ConflictRule | str = ConflictRule.FAIL_CLOSED
    budget: PolicyBudget | Mapping[str, Any] | None = None
    allowed_jurisdictions: tuple[str, ...] = ()
    allowed_tenants: tuple[str, ...] = ()
    description: str = ""
    schema_version: str = PROOF_TRUST_POLICY_SCHEMA_VERSION
    interface: str = PROOF_TRUST_POLICY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_id", _require_text(self.policy_id, "policy_id")
        )
        object.__setattr__(
            self, "corpus_roots", _unique_cids(self.corpus_roots, "corpus_roots")
        )
        object.__setattr__(
            self,
            "revocation_roots",
            _unique_cids(self.revocation_roots, "revocation_roots"),
        )
        object.__setattr__(
            self, "policy_roots", _unique_cids(self.policy_roots, "policy_roots")
        )
        object.__setattr__(
            self,
            "vk_registry_roots",
            _unique_cids(self.vk_registry_roots, "vk_registry_roots"),
        )
        object.__setattr__(
            self,
            "circuit_allowlist",
            _unique_texts(self.circuit_allowlist, "circuit_allowlist"),
        )
        object.__setattr__(
            self,
            "backend_allowlist",
            _unique_texts(self.backend_allowlist, "backend_allowlist"),
        )
        object.__setattr__(
            self,
            "solver_allowlist",
            _unique_texts(self.solver_allowlist, "solver_allowlist"),
        )
        object.__setattr__(
            self,
            "compiler_allowlist",
            _unique_texts(self.compiler_allowlist, "compiler_allowlist"),
        )
        object.__setattr__(
            self,
            "security_profile_allowlist",
            tuple(
                _require_profile(item, "security_profile_allowlist")
                for item in _unique_texts(
                    self.security_profile_allowlist, "security_profile_allowlist"
                )
            ),
        )

        attestation_allow = tuple(
            parse_attestation_kind(item).value
            for item in _unique_texts(
                self.attestation_kind_allowlist, "attestation_kind_allowlist"
            )
        )
        if not attestation_allow:
            raise ProofTrustPolicyError(
                "attestation_kind_allowlist must not be empty"
            )
        object.__setattr__(self, "attestation_kind_allowlist", attestation_allow)

        authoritative = tuple(
            parse_attestation_kind(item).value
            for item in _unique_texts(
                self.authoritative_attestation_kinds,
                "authoritative_attestation_kinds",
            )
        )
        if not authoritative:
            raise ProofTrustPolicyError(
                "authoritative_attestation_kinds must not be empty"
            )
        forbidden = set(authoritative) & _FORBIDDEN_THEOREM_KINDS
        if forbidden:
            raise ProofTrustPolicyError(
                "authoritative_attestation_kinds cannot include non-substitutable "
                f"non-theorem evidence: {', '.join(sorted(forbidden))}"
            )
        # Direct verification is always required in the authoritative set so
        # policy cannot silently drop it in favour of weaker vouchers only.
        if AttestationKind.DIRECT_PROOF_VERIFICATION.value not in authoritative:
            raise ProofTrustPolicyError(
                "authoritative_attestation_kinds must include "
                "direct-proof-verification"
            )
        object.__setattr__(self, "authoritative_attestation_kinds", authoritative)

        object.__setattr__(
            self,
            "required_result_authority",
            parse_result_authority(self.required_result_authority),
        )
        object.__setattr__(
            self,
            "minimum_security_profile",
            _optional_profile(
                self.minimum_security_profile, "minimum_security_profile"
            ),
        )

        for flag_name in (
            "accept_simulated",
            "accept_membership_as_theorem",
            "accept_signature_as_theorem",
            "require_circuit_binding",
            "require_vk_binding",
            "require_public_inputs",
        ):
            flag = getattr(self, flag_name)
            if not isinstance(flag, bool):
                raise ProofTrustPolicyError(f"{flag_name} must be a bool")

        # Hard fail-closed: these flags exist for explicit adversarial tests
        # but cannot be true on a production trust policy.
        if self.accept_membership_as_theorem:
            raise ProofTrustPolicyError(
                "accept_membership_as_theorem is forbidden; "
                "artifact-membership is non-substitutable"
            )
        if self.accept_signature_as_theorem:
            raise ProofTrustPolicyError(
                "accept_signature_as_theorem is forbidden; "
                "signature evidence is non-substitutable"
            )
        if self.accept_simulated and (
            AttestationKind.SIMULATION.value in authoritative
        ):
            raise ProofTrustPolicyError(
                "simulation cannot be listed as authoritative attestation"
            )

        object.__setattr__(
            self, "world_mode", _parse_enum(self.world_mode, WorldMode, "world_mode")
        )
        object.__setattr__(
            self,
            "conflict_rule",
            _parse_enum(self.conflict_rule, ConflictRule, "conflict_rule"),
        )

        budget = self.budget
        if budget is None:
            budget = PolicyBudget()
        elif not isinstance(budget, PolicyBudget):
            budget = PolicyBudget.from_dict(budget)
        object.__setattr__(self, "budget", budget)

        object.__setattr__(
            self,
            "allowed_jurisdictions",
            tuple(
                _require_profile(item, "allowed_jurisdictions")
                for item in _unique_texts(
                    self.allowed_jurisdictions, "allowed_jurisdictions"
                )
            ),
        )
        object.__setattr__(
            self,
            "allowed_tenants",
            _unique_texts(self.allowed_tenants, "allowed_tenants"),
        )
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_TRUST_POLICY_SCHEMA_VERSION:
            raise ProofTrustPolicyError(
                f"unsupported trust policy schema: {self.schema_version!r}"
            )
        if self.interface != PROOF_TRUST_POLICY_INTERFACE:
            raise ProofTrustPolicyError(
                f"unsupported trust policy interface: {self.interface!r}"
            )

        # Open-world cannot treat absence as fail-as-false permission.
        if self.world_mode is WorldMode.OPEN and self.conflict_rule is ConflictRule.DENY_OVERRIDES:
            # Still valid: deny still overrides when both present; absence is
            # unknown, not allow.  No further restriction required.
            pass

    # -- identity -------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        assert isinstance(self.budget, PolicyBudget)
        assert isinstance(self.required_result_authority, AuthorityKind)
        return {
            "accept_membership_as_theorem": self.accept_membership_as_theorem,
            "accept_signature_as_theorem": self.accept_signature_as_theorem,
            "accept_simulated": self.accept_simulated,
            "allowed_jurisdictions": list(self.allowed_jurisdictions),
            "allowed_tenants": list(self.allowed_tenants),
            "attestation_kind_allowlist": list(self.attestation_kind_allowlist),
            "authoritative_attestation_kinds": list(
                self.authoritative_attestation_kinds
            ),
            "backend_allowlist": list(self.backend_allowlist),
            "budget": self.budget.to_dict(),
            "circuit_allowlist": list(self.circuit_allowlist),
            "compiler_allowlist": list(self.compiler_allowlist),
            "conflict_rule": self.conflict_rule.value,
            "corpus_roots": list(self.corpus_roots),
            "description": self.description,
            "interface": self.interface,
            "minimum_security_profile": self.minimum_security_profile,
            "non_substitutable_evidence": sorted(NON_SUBSTITUTABLE_POLICY_EVIDENCE),
            "policy_id": self.policy_id,
            "policy_roots": list(self.policy_roots),
            "require_circuit_binding": self.require_circuit_binding,
            "require_public_inputs": self.require_public_inputs,
            "require_vk_binding": self.require_vk_binding,
            "required_result_authority": self.required_result_authority.value,
            "revocation_roots": list(self.revocation_roots),
            "schema_version": self.schema_version,
            "security_profile_allowlist": list(self.security_profile_allowlist),
            "solver_allowlist": list(self.solver_allowlist),
            "vk_registry_roots": list(self.vk_registry_roots),
            "world_mode": self.world_mode.value,
        }

    def policy_digest(self) -> str:
        """Return canonical ``sha256:<hex>`` digest of the policy map."""

        return _sha256_digest(_canonical_bytes(self.to_dict()))

    @classmethod
    def from_dict(cls, value: Any) -> "ProofTrustPolicy":
        payload = dict(_as_mapping(value, "proof trust policy"))
        # non_substitutable_evidence is emitted for consumers; ignore on load.
        payload.pop("non_substitutable_evidence", None)
        _reject_unknown(
            payload,
            frozenset(
                {
                    "accept_membership_as_theorem",
                    "accept_signature_as_theorem",
                    "accept_simulated",
                    "allowed_jurisdictions",
                    "allowed_tenants",
                    "attestation_kind_allowlist",
                    "authoritative_attestation_kinds",
                    "backend_allowlist",
                    "budget",
                    "circuit_allowlist",
                    "compiler_allowlist",
                    "conflict_rule",
                    "corpus_roots",
                    "description",
                    "interface",
                    "minimum_security_profile",
                    "policy_id",
                    "policy_roots",
                    "require_circuit_binding",
                    "require_public_inputs",
                    "require_vk_binding",
                    "required_result_authority",
                    "revocation_roots",
                    "schema_version",
                    "security_profile_allowlist",
                    "solver_allowlist",
                    "vk_registry_roots",
                    "world_mode",
                }
            ),
            "proof trust policy",
        )
        return cls(
            policy_id=payload.get("policy_id", ""),
            corpus_roots=tuple(payload.get("corpus_roots", ()) or ()),
            revocation_roots=tuple(payload.get("revocation_roots", ()) or ()),
            policy_roots=tuple(payload.get("policy_roots", ()) or ()),
            vk_registry_roots=tuple(payload.get("vk_registry_roots", ()) or ()),
            circuit_allowlist=tuple(payload.get("circuit_allowlist", ()) or ()),
            backend_allowlist=tuple(payload.get("backend_allowlist", ()) or ()),
            solver_allowlist=tuple(payload.get("solver_allowlist", ()) or ()),
            compiler_allowlist=tuple(payload.get("compiler_allowlist", ()) or ()),
            security_profile_allowlist=tuple(
                payload.get("security_profile_allowlist", ()) or ()
            ),
            attestation_kind_allowlist=tuple(
                payload.get(
                    "attestation_kind_allowlist",
                    (AttestationKind.DIRECT_PROOF_VERIFICATION.value,),
                )
                or (AttestationKind.DIRECT_PROOF_VERIFICATION.value,)
            ),
            authoritative_attestation_kinds=tuple(
                payload.get(
                    "authoritative_attestation_kinds",
                    (AttestationKind.DIRECT_PROOF_VERIFICATION.value,),
                )
                or (AttestationKind.DIRECT_PROOF_VERIFICATION.value,)
            ),
            required_result_authority=payload.get(
                "required_result_authority", AuthorityKind.THEOREM_PROOF.value
            ),
            minimum_security_profile=payload.get("minimum_security_profile", ""),
            accept_simulated=bool(payload.get("accept_simulated", False)),
            accept_membership_as_theorem=bool(
                payload.get("accept_membership_as_theorem", False)
            ),
            accept_signature_as_theorem=bool(
                payload.get("accept_signature_as_theorem", False)
            ),
            require_circuit_binding=bool(
                payload.get("require_circuit_binding", True)
            ),
            require_vk_binding=bool(payload.get("require_vk_binding", True)),
            require_public_inputs=bool(
                payload.get("require_public_inputs", True)
            ),
            world_mode=payload.get("world_mode", WorldMode.CLOSED.value),
            conflict_rule=payload.get(
                "conflict_rule", ConflictRule.FAIL_CLOSED.value
            ),
            budget=payload.get("budget"),
            allowed_jurisdictions=tuple(
                payload.get("allowed_jurisdictions", ()) or ()
            ),
            allowed_tenants=tuple(payload.get("allowed_tenants", ()) or ()),
            description=payload.get("description", ""),
            schema_version=payload.get(
                "schema_version", PROOF_TRUST_POLICY_SCHEMA_VERSION
            ),
            interface=payload.get("interface", PROOF_TRUST_POLICY_INTERFACE),
        )

    # -- evaluation -----------------------------------------------------------

    def admits_attestation_kind(self, kind: AttestationKind | str) -> bool:
        parsed = parse_attestation_kind(kind)
        if parsed is AttestationKind.SIMULATION and not self.accept_simulated:
            return False
        return parsed.value in self.attestation_kind_allowlist

    def treats_as_authoritative(self, kind: AttestationKind | str) -> bool:
        """Return whether *kind* may carry the required result authority.

        Membership, signature, and simulation never qualify.  Verifier
        execution qualifies only when explicitly listed in
        ``authoritative_attestation_kinds`` (and still never replaces the
        requirement that direct-proof-verification remains in that set).
        """

        parsed = parse_attestation_kind(kind)
        if parsed.value in _FORBIDDEN_THEOREM_KINDS:
            return False
        if parsed is AttestationKind.SIMULATION:
            return False
        return parsed.value in self.authoritative_attestation_kinds

    def evaluate(
        self,
        envelope: AttestedProofEnvelope,
        *,
        at_time: str = "",
        raise_on_reject: bool = False,
    ) -> TrustPolicyEvaluation:
        """Evaluate *envelope* under this policy (fail closed)."""

        if not isinstance(envelope, AttestedProofEnvelope):
            raise ProofTrustPolicyError(
                "envelope must be an AttestedProofEnvelope"
            )
        envelope.verify_integrity()
        reasons: list[str] = []

        kind = envelope.attestation_kind
        if not self.admits_attestation_kind(kind):
            reasons.append(f"attestation_kind_not_allowlisted:{kind.value}")

        # Non-substitutability: simulation / membership / signature alone.
        if kind is AttestationKind.SIMULATION and not self.accept_simulated:
            reasons.append("simulation_rejected")
        if kind is AttestationKind.ARTIFACT_MEMBERSHIP:
            reasons.append("membership_not_theorem_authority")
        if (
            envelope.has_signature_evidence
            and kind is not AttestationKind.DIRECT_PROOF_VERIFICATION
            and kind is not AttestationKind.VERIFIER_EXECUTION
        ):
            # Signature-only envelopes use membership or empty kinds; flag.
            if kind is AttestationKind.ARTIFACT_MEMBERSHIP or not self.treats_as_authoritative(
                kind
            ):
                reasons.append("signature_not_theorem_authority")

        assert isinstance(self.required_result_authority, AuthorityKind)
        if envelope.result_authority is not self.required_result_authority:
            reasons.append(
                "result_authority_mismatch:"
                f"{envelope.result_authority.value}!="
                f"{self.required_result_authority.value}"
            )

        # Authoritative path requires both allowlist and authority set.
        if not self.treats_as_authoritative(kind):
            if kind is AttestationKind.VERIFIER_EXECUTION:
                reasons.append("verifier_execution_not_authoritative")
            elif kind is AttestationKind.DIRECT_PROOF_VERIFICATION:
                reasons.append("direct_verification_not_authoritative")
            else:
                reasons.append(f"attestation_kind_non_authoritative:{kind.value}")

        # Exact roots when declared by policy.
        if self.corpus_roots:
            if not envelope.corpus_root_cid:
                reasons.append("missing_corpus_root")
            elif envelope.corpus_root_cid not in self.corpus_roots:
                reasons.append("corpus_root_not_exact")
        if self.revocation_roots:
            if not envelope.revocation_root_cid:
                reasons.append("missing_revocation_root")
            elif envelope.revocation_root_cid not in self.revocation_roots:
                reasons.append("revocation_root_not_exact")

        # Allowlists (empty allowlist means unrestricted for that dimension).
        circuit = envelope.circuit
        if self.circuit_allowlist:
            circuit_id = getattr(circuit, "circuit_id", "") or ""
            circuit_ref = getattr(circuit, "circuit_ref", "") or ""
            if circuit_id not in self.circuit_allowlist and circuit_ref not in self.circuit_allowlist:
                reasons.append("circuit_not_allowlisted")
        if self.backend_allowlist:
            backend = envelope.backend_id or getattr(circuit, "backend_id", "")
            if backend not in self.backend_allowlist:
                reasons.append("backend_not_allowlisted")
        if self.solver_allowlist and envelope.solver_id:
            if envelope.solver_id not in self.solver_allowlist:
                reasons.append("solver_not_allowlisted")
        if self.compiler_allowlist and envelope.compiler_id:
            if envelope.compiler_id not in self.compiler_allowlist:
                reasons.append("compiler_not_allowlisted")
        if self.security_profile_allowlist:
            profile = envelope.security_profile or getattr(
                circuit, "security_profile", ""
            )
            if profile not in self.security_profile_allowlist:
                reasons.append("security_profile_not_allowlisted")
        if self.minimum_security_profile:
            profile = envelope.security_profile or getattr(
                circuit, "security_profile", ""
            )
            if not profile:
                reasons.append("missing_security_profile")
            elif profile != self.minimum_security_profile and (
                not self.security_profile_allowlist
                or profile not in self.security_profile_allowlist
            ):
                # Exact minimum identity when no broader allowlist is set.
                if not self.security_profile_allowlist:
                    reasons.append("security_profile_below_minimum")

        if self.require_circuit_binding:
            if not getattr(circuit, "circuit_id", ""):
                reasons.append("missing_circuit_binding")
        if self.require_vk_binding:
            if not getattr(circuit, "vk_id", "") and not getattr(
                circuit, "vk_digest", ""
            ):
                reasons.append("missing_vk_binding")
        if self.require_public_inputs:
            public_inputs = dict(envelope.public_inputs) or dict(
                getattr(circuit, "public_inputs", {}) or {}
            )
            if not public_inputs:
                reasons.append("missing_public_inputs")

        if envelope.is_revoked():
            reasons.append("envelope_revoked")
        if envelope.is_superseded():
            reasons.append("envelope_superseded")
        if at_time:
            if not envelope.temporal.is_effective_at(at_time):
                reasons.append("envelope_not_effective")

        if self.allowed_jurisdictions:
            jurisdiction = envelope.scope.jurisdiction
            if jurisdiction and jurisdiction not in self.allowed_jurisdictions:
                reasons.append("jurisdiction_not_allowed")
            if not jurisdiction:
                reasons.append("missing_jurisdiction")
        if self.allowed_tenants:
            tenant = envelope.scope.tenant
            if tenant and tenant not in self.allowed_tenants:
                reasons.append("tenant_not_allowed")
            if not tenant:
                reasons.append("missing_tenant")

        # Deduplicate reasons while preserving order.
        seen: set[str] = set()
        ordered: list[str] = []
        for reason in reasons:
            if reason not in seen:
                seen.add(reason)
                ordered.append(reason)

        if ordered:
            # Fail closed: policy violations reject.  ABSTAIN is reserved for
            # incomplete-but-benign gaps (unused by current hard checks).
            hard = any(
                token in reason
                for reason in ordered
                for token in (
                    "simulation_rejected",
                    "membership_not_theorem",
                    "signature_not_theorem",
                    "result_authority_mismatch",
                    "not_allowlisted",
                    "not_exact",
                    "revoked",
                    "superseded",
                    "not_effective",
                    "non_authoritative",
                    "not_authoritative",
                    "forbidden",
                    "below_minimum",
                    "missing_",
                    "not_allowed",
                )
            )
            status = (
                TrustEvaluationStatus.REJECT
                if hard
                else TrustEvaluationStatus.ABSTAIN
            )
            evaluation = TrustPolicyEvaluation(
                status=status,
                reasons=tuple(ordered),
                accepted_attestation_kind="",
                required_result_authority=self.required_result_authority.value,
                policy_digest=self.policy_digest(),
                envelope_cid=envelope.envelope_cid,
            )
            if raise_on_reject:
                raise ProofTrustPolicyViolation(
                    "trust policy rejected envelope: " + "; ".join(ordered)
                )
            return evaluation

        return TrustPolicyEvaluation(
            status=TrustEvaluationStatus.ACCEPT,
            reasons=(),
            accepted_attestation_kind=kind.value,
            required_result_authority=self.required_result_authority.value,
            policy_digest=self.policy_digest(),
            envelope_cid=envelope.envelope_cid,
        )


def default_production_trust_policy(
    *,
    policy_id: str = "proof-trust-production",
    corpus_roots: Sequence[str] = (),
    revocation_roots: Sequence[str] = (),
) -> ProofTrustPolicy:
    """Return a fail-closed production trust policy."""

    return ProofTrustPolicy(
        policy_id=policy_id,
        corpus_roots=tuple(corpus_roots),
        revocation_roots=tuple(revocation_roots),
        attestation_kind_allowlist=(
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
        ),
        authoritative_attestation_kinds=(
            AttestationKind.DIRECT_PROOF_VERIFICATION.value,
        ),
        required_result_authority=AuthorityKind.THEOREM_PROOF,
        accept_simulated=False,
        require_circuit_binding=True,
        require_vk_binding=True,
        require_public_inputs=True,
        world_mode=WorldMode.CLOSED,
        conflict_rule=ConflictRule.FAIL_CLOSED,
        description=(
            "Production trust policy: direct proof verification only; "
            "simulation, membership, and signature are non-substitutable."
        ),
    )


# ---------------------------------------------------------------------------
# CorpusCoveragePolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CorpusCoveragePolicy:
    """Coverage requirements before ranking or allow (CorpusCoveragePolicy@1)."""

    policy_id: str
    required_domains: tuple[str, ...] = ()
    required_families: tuple[str, ...] = ()
    required_selectors: tuple[str, ...] = ()
    require_complete: bool = True
    max_gap_kinds: int = 0
    allowed_gap_kinds: tuple[str, ...] = ()
    minimum_covered_selector_count: int = 0
    description: str = ""
    schema_version: str = CORPUS_COVERAGE_POLICY_SCHEMA_VERSION
    interface: str = CORPUS_COVERAGE_POLICY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_id", _require_text(self.policy_id, "policy_id")
        )
        object.__setattr__(
            self,
            "required_domains",
            _unique_texts(self.required_domains, "required_domains"),
        )
        object.__setattr__(
            self,
            "required_families",
            _unique_texts(self.required_families, "required_families"),
        )
        object.__setattr__(
            self,
            "required_selectors",
            _unique_texts(self.required_selectors, "required_selectors"),
        )
        if not isinstance(self.require_complete, bool):
            raise ProofTrustPolicyError("require_complete must be a bool")
        object.__setattr__(
            self,
            "max_gap_kinds",
            _non_negative_int(self.max_gap_kinds, "max_gap_kinds"),
        )
        object.__setattr__(
            self,
            "allowed_gap_kinds",
            _unique_texts(self.allowed_gap_kinds, "allowed_gap_kinds"),
        )
        object.__setattr__(
            self,
            "minimum_covered_selector_count",
            _non_negative_int(
                self.minimum_covered_selector_count,
                "minimum_covered_selector_count",
            ),
        )
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != CORPUS_COVERAGE_POLICY_SCHEMA_VERSION:
            raise ProofTrustPolicyError(
                f"unsupported coverage policy schema: {self.schema_version!r}"
            )
        if self.interface != CORPUS_COVERAGE_POLICY_INTERFACE:
            raise ProofTrustPolicyError(
                f"unsupported coverage policy interface: {self.interface!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_gap_kinds": list(self.allowed_gap_kinds),
            "description": self.description,
            "interface": self.interface,
            "max_gap_kinds": self.max_gap_kinds,
            "minimum_covered_selector_count": self.minimum_covered_selector_count,
            "policy_id": self.policy_id,
            "require_complete": self.require_complete,
            "required_domains": list(self.required_domains),
            "required_families": list(self.required_families),
            "required_selectors": list(self.required_selectors),
            "schema_version": self.schema_version,
        }

    def policy_digest(self) -> str:
        return _sha256_digest(_canonical_bytes(self.to_dict()))

    @classmethod
    def from_dict(cls, value: Any) -> "CorpusCoveragePolicy":
        payload = dict(_as_mapping(value, "corpus coverage policy"))
        _reject_unknown(
            payload,
            frozenset(
                {
                    "allowed_gap_kinds",
                    "description",
                    "interface",
                    "max_gap_kinds",
                    "minimum_covered_selector_count",
                    "policy_id",
                    "require_complete",
                    "required_domains",
                    "required_families",
                    "required_selectors",
                    "schema_version",
                }
            ),
            "corpus coverage policy",
        )
        return cls(
            policy_id=payload.get("policy_id", ""),
            required_domains=tuple(payload.get("required_domains", ()) or ()),
            required_families=tuple(payload.get("required_families", ()) or ()),
            required_selectors=tuple(
                payload.get("required_selectors", ()) or ()
            ),
            require_complete=bool(payload.get("require_complete", True)),
            max_gap_kinds=int(payload.get("max_gap_kinds", 0)),
            allowed_gap_kinds=tuple(payload.get("allowed_gap_kinds", ()) or ()),
            minimum_covered_selector_count=int(
                payload.get("minimum_covered_selector_count", 0)
            ),
            description=payload.get("description", ""),
            schema_version=payload.get(
                "schema_version", CORPUS_COVERAGE_POLICY_SCHEMA_VERSION
            ),
            interface=payload.get(
                "interface", CORPUS_COVERAGE_POLICY_INTERFACE
            ),
        )

    def evaluate_coverage(
        self,
        coverage: CoverageDeclaration | Mapping[str, Any],
        *,
        domain: str = "",
        family: str = "",
    ) -> TrustPolicyEvaluation:
        """Evaluate a coverage declaration against this policy."""

        if not isinstance(coverage, CoverageDeclaration):
            coverage = CoverageDeclaration.from_dict(coverage)
        reasons: list[str] = []

        if self.required_domains and domain:
            if domain not in self.required_domains:
                reasons.append(f"domain_not_required:{domain}")
        if self.required_families and family:
            if family not in self.required_families:
                reasons.append(f"family_not_required:{family}")
        if self.require_complete and not coverage.complete:
            reasons.append("coverage_incomplete")
        if len(coverage.gap_kinds) > self.max_gap_kinds:
            reasons.append("too_many_coverage_gaps")
        if self.allowed_gap_kinds:
            for gap in coverage.gap_kinds:
                if gap not in self.allowed_gap_kinds:
                    reasons.append(f"disallowed_gap_kind:{gap}")
        if self.required_selectors:
            missing = [
                selector
                for selector in self.required_selectors
                if selector not in coverage.covered_selectors
            ]
            for selector in missing:
                reasons.append(f"missing_selector:{selector}")
        if (
            self.minimum_covered_selector_count
            and len(coverage.covered_selectors)
            < self.minimum_covered_selector_count
        ):
            reasons.append("insufficient_covered_selectors")

        if reasons:
            return TrustPolicyEvaluation(
                status=TrustEvaluationStatus.REJECT,
                reasons=tuple(reasons),
                policy_digest=self.policy_digest(),
            )
        return TrustPolicyEvaluation(
            status=TrustEvaluationStatus.ACCEPT,
            reasons=(),
            policy_digest=self.policy_digest(),
        )

    def evaluate_envelope(
        self, envelope: AttestedProofEnvelope
    ) -> TrustPolicyEvaluation:
        """Evaluate coverage declared on an attested proof envelope."""

        if not isinstance(envelope, AttestedProofEnvelope):
            raise ProofTrustPolicyError(
                "envelope must be an AttestedProofEnvelope"
            )
        return self.evaluate_coverage(
            envelope.coverage,
            domain=envelope.domain,
            family=envelope.family.value,
        )


__all__ = [
    "CORPUS_COVERAGE_POLICY_INTERFACE",
    "CORPUS_COVERAGE_POLICY_SCHEMA_VERSION",
    "NON_SUBSTITUTABLE_POLICY_EVIDENCE",
    "POLICY_BUDGET_SCHEMA_VERSION",
    "POLICY_EVALUATION_SCHEMA_VERSION",
    "PROOF_TRUST_POLICY_INTERFACE",
    "PROOF_TRUST_POLICY_SCHEMA_VERSION",
    "ConflictRule",
    "CorpusCoveragePolicy",
    "PolicyBudget",
    "ProofTrustPolicy",
    "ProofTrustPolicyError",
    "ProofTrustPolicyViolation",
    "TrustEvaluationStatus",
    "TrustPolicyEvaluation",
    "WorldMode",
    "default_production_trust_policy",
    "non_substitutable_evidence_kinds",
]
