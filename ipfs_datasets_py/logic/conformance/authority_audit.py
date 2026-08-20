"""Audit advisor, solver, Hammer, and proof-kernel authority boundaries (LFP-042).

``LogicAuthorityAudit@1`` is a side-effect-free authority-boundary evaluator.
It never installs tools, probes the host, opens the network, or upgrades a
claim.  Adversarial promotion scenarios are classified against closed rules:

* confidence / ``is_valid`` / similarity never prove parse correctness or mint
  proof authority;
* generic operational success (``ok``, ``success``, ``passed``) never becomes
  a theorem or kernel proof;
* quota exhaustion, timeout, and unavailability never become logic evidence;
* only official kernel success under pinned imports (and matching environment
  identity) establishes kernel / theorem authority.

The audit composes existing contracts from proposal advisors, toolchain roles,
capability-matrix ceilings, typed backend results, and kernel-target trust
receipts.  It does not mutate those modules.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolchainAuthorityCeiling,
    ToolRole,
    can_satisfy_certified_authority_requirement,
    evaluate_role_aware_promotion,
    get_tool_role,
)
from ipfs_datasets_py.logic.conformance.matrix import (
    DEFAULT_MATRIX,
    AuthorityCeiling,
)
from ipfs_datasets_py.logic.formalization.proposal_advisors import (
    UNVERIFIED_AUTHORITY,
    confidence_never_yields_proof,
)
from ipfs_datasets_py.logic.parsers.kernel_targets import (
    DEFAULT_ISABELLE_IMPORTS,
    DEFAULT_LEAN_IMPORTS,
    DEFAULT_ROCQ_IMPORTS,
    KernelTargetKind,
    ProofAuthorityRole,
    RouteSurface,
    is_official_kernel,
    result_authority_for_surface,
    surface_authority_role,
)

# ---------------------------------------------------------------------------
# Interface / schema
# ---------------------------------------------------------------------------

LOGIC_AUTHORITY_AUDIT_INTERFACE: Final = "LogicAuthorityAudit@1"
LOGIC_AUTHORITY_AUDIT_SCHEMA: Final = "logic-authority-audit/v1"
LOGIC_AUTHORITY_AUDIT_REPORT_SCHEMA: Final = "logic-authority-audit-report/v1"
LOGIC_AUTHORITY_CLAIM_SCHEMA: Final = "logic-authority-claim/v1"
LOGIC_AUTHORITY_VERDICT_SCHEMA: Final = "logic-authority-verdict/v1"
AUDIT_REPORT_VERSION: Final = "1.0.0"
TASK_ID: Final = "LFP-042"
GOAL_ID: Final = "LFP-G080"
PROGRAM_ID: Final = "ipfs-datasets-logic-family-parser-v1"

# Closed reason codes (stable for golden / differential consumers).
REASON_CONFIDENCE_NOT_PROOF: Final = "confidence_never_proves_parse_correctness"
REASON_GENERIC_SUCCESS_NOT_PROOF: Final = "generic_success_never_becomes_proof"
REASON_QUOTA_NOT_LOGIC_EVIDENCE: Final = "quota_unavailability_never_logic_evidence"
REASON_KERNEL_REQUIRES_OFFICIAL: Final = "kernel_authority_requires_official_kernel"
REASON_KERNEL_REQUIRES_PINNED_IMPORTS: Final = "kernel_authority_requires_pinned_imports"
REASON_KERNEL_REQUIRES_ACCEPTANCE: Final = "kernel_authority_requires_kernel_acceptance"
REASON_KERNEL_REQUIRES_ENVIRONMENT: Final = "kernel_authority_requires_pinned_environment"
REASON_ADVISOR_CEILING: Final = "advisor_ceiling_is_unverified_candidate"
REASON_HAMMER_CANDIDATE: Final = "hammer_remains_candidate_until_reconstruction"
REASON_SOLVER_NOT_KERNEL: Final = "solver_authority_is_not_kernel"
REASON_BOUNDED_NOT_KERNEL: Final = "bounded_authority_is_not_kernel"
REASON_MONITOR_NOT_KERNEL: Final = "monitor_authority_is_finite_trace_only"
REASON_PROTOCOL_NOT_KERNEL: Final = "protocol_authority_is_not_kernel"
REASON_ROLE_CANNOT_CERTIFY: Final = "role_cannot_satisfy_certified_authority"
REASON_PRESENCE_NOT_AUTHORITY: Final = "presence_alone_is_not_authority"
REASON_KERNEL_AUTHORITY_ESTABLISHED: Final = "official_kernel_success_under_pinned_imports"
REASON_SCOPED_AUTHORITY: Final = "scoped_non_kernel_authority_allowed"
REASON_CLAIM_REJECTED: Final = "authority_claim_rejected"

# Operational tokens that never establish logic conclusions.
_GENERIC_SUCCESS_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "ok",
        "okay",
        "success",
        "successful",
        "passed",
        "pass",
        "done",
        "complete",
        "completed",
        "true",
        "yes",
        "1",
    }
)

_QUOTA_UNAVAILABILITY_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "unavailable",
        "timeout",
        "timed_out",
        "quota",
        "quota_exceeded",
        "rate_limited",
        "rate_limit",
        "resource_exhausted",
        "budget_exhausted",
        "capacity_exceeded",
        "not_installed",
        "missing_binary",
        "tool_missing",
        "error",
        "unknown",
        "unsupported",
        "malformed",
    }
)

_KERNEL_PROVIDER_IDS: Final[frozenset[str]] = frozenset(
    {"lean", "rocq", "isabelle", "coq"}
)
_ADVISOR_PROVIDER_IDS: Final[frozenset[str]] = frozenset(
    {
        "symbolicai",
        "symai",
        "ergoai",
        "ergo_ai",
        "leanstral",
        "autoencoder",
    }
)
_HAMMER_PROVIDER_IDS: Final[frozenset[str]] = frozenset({"hammer"})
_SMT_PROVIDER_IDS: Final[frozenset[str]] = frozenset({"z3", "cvc5"})
_ATP_PROVIDER_IDS: Final[frozenset[str]] = frozenset({"vampire", "eprover", "e"})
_MODEL_CHECKER_IDS: Final[frozenset[str]] = frozenset(
    {"tla_tlc", "tlc", "apalache"}
)
_PROTOCOL_PROVIDER_IDS: Final[frozenset[str]] = frozenset(
    {"proverif", "tamarin"}
)
_MONITOR_PROVIDER_IDS: Final[frozenset[str]] = frozenset(
    {"runtime_mtl", "runtime-mtl", "runtime-mtl-external"}
)

_PINNED_IMPORTS_BY_KERNEL: Final[dict[str, tuple[str, ...]]] = {
    "lean": DEFAULT_LEAN_IMPORTS,
    "rocq": DEFAULT_ROCQ_IMPORTS,
    "coq": DEFAULT_ROCQ_IMPORTS,
    "isabelle": DEFAULT_ISABELLE_IMPORTS,
}

# Evidence subset required by LFP-042.
REQUIRED_EVIDENCE_SUBSET: Final[tuple[str, ...]] = (
    "symai",
    "ergoai",
    "advisor",
    "candidate",
    "hammer",
    "premise",
    "solver",
    "model_checker",
    "bounded",
    "monitor",
    "kernel",
    "axiom",
    "imports",
)


class AuthorityAuditError(ValueError):
    """Raised when an authority-audit contract is malformed."""


class ActorKind(StrEnum):
    """Closed participation kinds audited by this module."""

    ADVISOR = "advisor"
    CANDIDATE = "candidate"
    HAMMER = "hammer"
    SOLVER = "solver"
    ATP = "atp"
    MODEL_CHECKER = "model_checker"
    PROTOCOL = "protocol"
    MONITOR = "monitor"
    KERNEL = "kernel"
    SUPPORT = "support"
    UNKNOWN = "unknown"


class ClaimedAuthority(StrEnum):
    """Authority a claim attempts to assert (may be rejected)."""

    NONE = "none"
    ADVISORY = "advisory"
    CANDIDATE = "candidate"
    PARSE_CORRECT = "parse_correct"
    SATISFIABILITY = "satisfiability"
    BOUNDED = "bounded"
    PROTOCOL = "protocol"
    MONITOR = "monitor"
    AUTHORIZATION = "authorization"
    RECONSTRUCTION = "reconstruction"
    THEOREM = "theorem"
    KERNEL = "kernel"


class AuditDisposition(StrEnum):
    """How the audit classifies a claim."""

    REJECT = "reject"
    INCONCLUSIVE = "inconclusive"
    SCOPED = "scoped"
    KERNEL = "kernel"


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and (value is None or value == ""):
        return ""
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise AuthorityAuditError(
            f"{field_name} must be a non-empty trimmed string without NUL"
        )
    return value


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip())
    except ValueError as exc:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise AuthorityAuditError(
            f"{field_name} must be one of {choices}"
        ) from exc


def _normalize_token(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value).strip().lower()
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return text


def _stable_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def classify_actor(provider_id: str | object) -> ActorKind:
    """Map a provider / tool id to a closed actor kind."""

    key = _normalize_token(provider_id)
    if not key:
        return ActorKind.UNKNOWN
    if key in _KERNEL_PROVIDER_IDS:
        return ActorKind.KERNEL
    try:
        if is_official_kernel(key):
            return ActorKind.KERNEL
    except Exception:
        pass
    if key in _ADVISOR_PROVIDER_IDS:
        return ActorKind.ADVISOR
    if key in _HAMMER_PROVIDER_IDS:
        return ActorKind.HAMMER
    if key in _SMT_PROVIDER_IDS:
        return ActorKind.SOLVER
    if key in _ATP_PROVIDER_IDS:
        return ActorKind.ATP
    if key in _MODEL_CHECKER_IDS:
        return ActorKind.MODEL_CHECKER
    if key in _PROTOCOL_PROVIDER_IDS:
        return ActorKind.PROTOCOL
    if key in _MONITOR_PROVIDER_IDS:
        return ActorKind.MONITOR
    if key in {"java", "maude", "opam", "stack", "temurin_jdk", "temurin-jdk"}:
        return ActorKind.SUPPORT
    # Role matrix fallback for locked tool ids.
    role_key = {
        "rocq": "coq",
        "symai": "symbolicai",
        "tla_tlc": "tlc",
        "runtime_mtl": "runtime-mtl",
        "e": "eprover",
    }.get(key, key)
    try:
        role = get_tool_role(role_key)
    except Exception:
        role = None
    if role is not None:
        if role.role is ToolRole.ADVISOR:
            return ActorKind.ADVISOR
        if role.role is ToolRole.CANDIDATE:
            return ActorKind.CANDIDATE
        if role.role is ToolRole.SUPPORT:
            return ActorKind.SUPPORT
        if role.authority_ceiling is ToolchainAuthorityCeiling.KERNEL:
            return ActorKind.KERNEL
        if role.authority_ceiling is ToolchainAuthorityCeiling.SATISFIABILITY:
            return ActorKind.SOLVER
        if role.authority_ceiling is ToolchainAuthorityCeiling.RECONSTRUCTION:
            return ActorKind.ATP
        if role.authority_ceiling is ToolchainAuthorityCeiling.BOUNDED:
            return ActorKind.MODEL_CHECKER
        if role.authority_ceiling is ToolchainAuthorityCeiling.PROTOCOL:
            return ActorKind.PROTOCOL
        if role.authority_ceiling is ToolchainAuthorityCeiling.FINITE_TRACE:
            return ActorKind.MONITOR
    return ActorKind.UNKNOWN


def matrix_authority_ceiling(provider_id: str) -> AuthorityCeiling | None:
    """Return the matrix authority ceiling for a baseline provider, if any."""

    key = _normalize_token(provider_id)
    aliases = {
        "symai": "symbolicai",
        "ergo_ai": "ergoai",
        "tlc": "tla_tlc",
        "e": "eprover",
        "coq": "rocq",
    }
    resolved = aliases.get(key, key)
    for provider in DEFAULT_MATRIX.providers:
        if provider.provider_id == resolved:
            return provider.authority_ceiling
        if resolved in {alias.lower() for alias in provider.aliases}:
            return provider.authority_ceiling
    return None


def confidence_never_proves_parse_correctness(
    *,
    confidence: float | None = None,
    is_valid: bool | None = None,
    similarity: float | None = None,
    parse_ok: bool | None = None,
) -> bool:
    """Documented invariant: model scores never establish parse correctness.

    Always returns ``False`` (not proved / not parse-authoritative).  Arguments
    are accepted so call sites can pass through legacy fields without elevating
    them.  High confidence with ``parse_ok=True`` still yields ``False``.
    """

    # Compose the proposal-advisor invariant; never elevate parse_ok alone.
    del parse_ok
    return confidence_never_yields_proof(
        is_valid=is_valid,
        confidence=confidence,
        similarity=similarity,
    )


def is_generic_success_token(status: object) -> bool:
    """Return True when ``status`` is a generic operational success token."""

    return _normalize_token(status) in _GENERIC_SUCCESS_TOKENS


def is_quota_or_unavailability_token(status: object) -> bool:
    """Return True when ``status`` is quota / timeout / unavailability."""

    token = _normalize_token(status)
    if not token:
        return False
    if token in _QUOTA_UNAVAILABILITY_TOKENS:
        return True
    return any(
        marker in token
        for marker in (
            "quota",
            "unavail",
            "timeout",
            "rate_limit",
            "exhaust",
            "not_installed",
            "missing",
        )
    )


def generic_success_never_becomes_proof(
    *,
    status: object = None,
    success: bool | None = None,
    exit_code: int | None = None,
) -> bool:
    """Generic operational success never establishes theorem / kernel proof.

    Always returns ``False`` (not proved).
    """

    del status, success, exit_code
    return False


def quota_unavailability_never_logic_evidence(
    *,
    status: object = None,
    reason: object = None,
    available: bool | None = None,
) -> bool:
    """Quota / unavailability / timeout never count as logic evidence.

    Returns ``False`` when the inputs are operational non-conclusions, and
    ``False`` for any attempt to treat them as conclusive logic evidence.
    The function is intentionally fail-closed: it never returns ``True``.
    """

    del status, reason, available
    return False


def has_pinned_imports(
    imports: Sequence[str] | None,
    *,
    kernel_target: str | KernelTargetKind | None = None,
) -> bool:
    """Return True when imports are non-empty and match the kernel pin when known."""

    if imports is None:
        return False
    cleaned = tuple(
        item.strip()
        for item in imports
        if isinstance(item, str) and item.strip()
    )
    if not cleaned:
        return False
    if kernel_target is None:
        return True
    key = _normalize_token(
        kernel_target.value
        if isinstance(kernel_target, KernelTargetKind)
        else kernel_target
    )
    expected = _PINNED_IMPORTS_BY_KERNEL.get(key)
    if expected is None:
        # Unknown kernel still requires non-empty pinned imports.
        return bool(cleaned)
    # Pinned imports must include every default import for the kernel target.
    return set(expected).issubset(set(cleaned))


def establishes_kernel_authority(
    *,
    provider_id: str | None = None,
    kernel_target: str | KernelTargetKind | None = None,
    kernel_accepted: bool = False,
    official_kernel: bool | None = None,
    imports: Sequence[str] | None = None,
    environment_pinned: bool = False,
    environment_id: str = "",
    trust_escapes_rejected: bool = True,
    status: object = None,
    claimed: ClaimedAuthority | str = ClaimedAuthority.KERNEL,
) -> bool:
    """Return True only for official kernel success under pinned imports.

    All of the following are required:

    * actor is an official kernel (lean / rocq / isabelle);
    * ``kernel_accepted`` is True;
    * imports are pinned (non-empty; include defaults when target known);
    * environment identity is pinned;
    * trust escapes remain rejected;
    * status is not quota / unavailability / generic-success-only.
    """

    claimed_auth = _enum(claimed, ClaimedAuthority, "claimed")
    if claimed_auth not in {ClaimedAuthority.KERNEL, ClaimedAuthority.THEOREM}:
        return False

    actor_key = _normalize_token(provider_id or kernel_target or "")
    if official_kernel is None:
        official = actor_key in _KERNEL_PROVIDER_IDS
        if not official and actor_key:
            try:
                official = is_official_kernel(actor_key)
            except Exception:
                official = False
    else:
        official = bool(official_kernel)
    if not official:
        return False
    if not kernel_accepted:
        return False
    if not has_pinned_imports(imports, kernel_target=kernel_target or actor_key):
        return False
    if not environment_pinned and not (
        isinstance(environment_id, str) and environment_id.strip()
    ):
        return False
    if not trust_escapes_rejected:
        return False
    if is_quota_or_unavailability_token(status):
        return False
    # Generic success alone is insufficient; acceptance flag is required above.
    if is_generic_success_token(status) and not kernel_accepted:
        return False
    return True


@dataclass(frozen=True, slots=True)
class AuthorityClaim:
    """One adversarial or honest authority claim under audit."""

    claim_id: str
    provider_id: str
    actor_kind: ActorKind | str = ActorKind.UNKNOWN
    claimed_authority: ClaimedAuthority | str = ClaimedAuthority.NONE
    confidence: float | None = None
    is_valid: bool | None = None
    similarity: float | None = None
    parse_ok: bool | None = None
    status: str = ""
    success: bool | None = None
    available: bool | None = None
    present: bool | None = None
    kernel_accepted: bool = False
    imports: tuple[str, ...] = ()
    axioms: tuple[str, ...] = ()
    environment_id: str = ""
    environment_pinned: bool = False
    trust_escapes_rejected: bool = True
    independent_reconstruction: bool = False
    notes: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LOGIC_AUTHORITY_CLAIM_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(
            self, "provider_id", _text(self.provider_id, "provider_id").lower()
        )
        actor = _enum(self.actor_kind, ActorKind, "actor_kind")
        if actor is ActorKind.UNKNOWN:
            actor = classify_actor(self.provider_id)
        object.__setattr__(self, "actor_kind", actor)
        object.__setattr__(
            self,
            "claimed_authority",
            _enum(self.claimed_authority, ClaimedAuthority, "claimed_authority"),
        )
        if self.confidence is not None:
            if not isinstance(self.confidence, (int, float)) or isinstance(
                self.confidence, bool
            ):
                raise AuthorityAuditError("confidence must be a number when set")
            object.__setattr__(self, "confidence", float(self.confidence))
        if self.similarity is not None:
            if not isinstance(self.similarity, (int, float)) or isinstance(
                self.similarity, bool
            ):
                raise AuthorityAuditError("similarity must be a number when set")
            object.__setattr__(self, "similarity", float(self.similarity))
        for flag_name in (
            "is_valid",
            "parse_ok",
            "success",
            "available",
            "present",
            "kernel_accepted",
            "environment_pinned",
            "trust_escapes_rejected",
            "independent_reconstruction",
        ):
            value = getattr(self, flag_name)
            if value is not None and not isinstance(value, bool):
                raise AuthorityAuditError(f"{flag_name} must be a boolean when set")
        object.__setattr__(
            self,
            "status",
            _text(self.status, "status", optional=True),
        )
        object.__setattr__(
            self,
            "imports",
            tuple(
                _text(item, "imports item")
                for item in (self.imports or ())
            ),
        )
        object.__setattr__(
            self,
            "axioms",
            tuple(_text(item, "axioms item") for item in (self.axioms or ())),
        )
        object.__setattr__(
            self,
            "environment_id",
            _text(self.environment_id, "environment_id", optional=True),
        )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes", optional=True)
        )
        if not isinstance(self.attributes, Mapping):
            raise AuthorityAuditError("attributes must be a mapping")
        object.__setattr__(
            self, "attributes", MappingProxyType(dict(self.attributes))
        )
        if self.schema_version != LOGIC_AUTHORITY_CLAIM_SCHEMA:
            raise AuthorityAuditError(
                f"claim schema must be {LOGIC_AUTHORITY_CLAIM_SCHEMA}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_kind": (
                self.actor_kind.value
                if isinstance(self.actor_kind, ActorKind)
                else self.actor_kind
            ),
            "attributes": dict(self.attributes),
            "available": self.available,
            "axioms": list(self.axioms),
            "claim_id": self.claim_id,
            "claimed_authority": (
                self.claimed_authority.value
                if isinstance(self.claimed_authority, ClaimedAuthority)
                else self.claimed_authority
            ),
            "confidence": self.confidence,
            "environment_id": self.environment_id,
            "environment_pinned": self.environment_pinned,
            "imports": list(self.imports),
            "independent_reconstruction": self.independent_reconstruction,
            "is_valid": self.is_valid,
            "kernel_accepted": self.kernel_accepted,
            "notes": self.notes,
            "parse_ok": self.parse_ok,
            "present": self.present,
            "provider_id": self.provider_id,
            "schema_version": self.schema_version,
            "similarity": self.similarity,
            "status": self.status,
            "success": self.success,
            "trust_escapes_rejected": self.trust_escapes_rejected,
        }


@dataclass(frozen=True, slots=True)
class AuthorityVerdict:
    """Typed disposition for one audited claim."""

    claim_id: str
    provider_id: str
    actor_kind: ActorKind | str
    claimed_authority: ClaimedAuthority | str
    disposition: AuditDisposition | str
    establishes_kernel_authority: bool
    establishes_proof: bool
    is_logic_evidence: bool
    reason_codes: tuple[str, ...]
    max_result_authority: ResultAuthority | str = ResultAuthority.CANDIDATE
    notes: str = ""
    schema_version: str = LOGIC_AUTHORITY_VERDICT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(
            self, "provider_id", _text(self.provider_id, "provider_id").lower()
        )
        object.__setattr__(
            self, "actor_kind", _enum(self.actor_kind, ActorKind, "actor_kind")
        )
        object.__setattr__(
            self,
            "claimed_authority",
            _enum(self.claimed_authority, ClaimedAuthority, "claimed_authority"),
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, AuditDisposition, "disposition"),
        )
        for flag_name in (
            "establishes_kernel_authority",
            "establishes_proof",
            "is_logic_evidence",
        ):
            if not isinstance(getattr(self, flag_name), bool):
                raise AuthorityAuditError(f"{flag_name} must be a boolean")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(_text(item, "reason_codes item") for item in self.reason_codes),
        )
        if not self.reason_codes:
            raise AuthorityAuditError("reason_codes must be non-empty")
        authority = self.max_result_authority
        if not isinstance(authority, ResultAuthority):
            authority = ResultAuthority(str(authority))
        object.__setattr__(self, "max_result_authority", authority)
        object.__setattr__(
            self, "notes", _text(self.notes, "notes", optional=True)
        )
        if self.schema_version != LOGIC_AUTHORITY_VERDICT_SCHEMA:
            raise AuthorityAuditError(
                f"verdict schema must be {LOGIC_AUTHORITY_VERDICT_SCHEMA}"
            )
        # Hard invariants: kernel proof implies official path.
        if self.establishes_kernel_authority and self.disposition is not AuditDisposition.KERNEL:
            raise AuthorityAuditError(
                "establishes_kernel_authority requires disposition=kernel"
            )
        if self.establishes_proof and self.disposition not in {
            AuditDisposition.KERNEL,
            AuditDisposition.SCOPED,
        }:
            raise AuthorityAuditError(
                "establishes_proof requires disposition kernel or scoped"
            )
        if (
            self.establishes_kernel_authority
            and self.max_result_authority is not ResultAuthority.THEOREM
        ):
            raise AuthorityAuditError(
                "kernel authority must expose theorem result authority"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_kind": (
                self.actor_kind.value
                if isinstance(self.actor_kind, ActorKind)
                else self.actor_kind
            ),
            "claim_id": self.claim_id,
            "claimed_authority": (
                self.claimed_authority.value
                if isinstance(self.claimed_authority, ClaimedAuthority)
                else self.claimed_authority
            ),
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, AuditDisposition)
                else self.disposition
            ),
            "establishes_kernel_authority": self.establishes_kernel_authority,
            "establishes_proof": self.establishes_proof,
            "is_logic_evidence": self.is_logic_evidence,
            "max_result_authority": (
                self.max_result_authority.value
                if isinstance(self.max_result_authority, ResultAuthority)
                else self.max_result_authority
            ),
            "notes": self.notes,
            "provider_id": self.provider_id,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
        }


def _max_authority_for_actor(actor: ActorKind) -> ResultAuthority:
    if actor is ActorKind.KERNEL:
        return ResultAuthority.THEOREM
    if actor is ActorKind.SOLVER:
        return ResultAuthority.SATISFIABILITY
    if actor is ActorKind.MODEL_CHECKER:
        return ResultAuthority.MODEL_CHECK
    if actor is ActorKind.PROTOCOL:
        return ResultAuthority.PROTOCOL
    if actor is ActorKind.MONITOR:
        return ResultAuthority.MONITOR
    if actor is ActorKind.ATP:
        return ResultAuthority.RECONSTRUCTION
    if actor is ActorKind.HAMMER:
        return ResultAuthority.CANDIDATE
    return ResultAuthority.CANDIDATE


def _scoped_reason(actor: ActorKind) -> str:
    if actor is ActorKind.SOLVER:
        return REASON_SOLVER_NOT_KERNEL
    if actor is ActorKind.MODEL_CHECKER:
        return REASON_BOUNDED_NOT_KERNEL
    if actor is ActorKind.MONITOR:
        return REASON_MONITOR_NOT_KERNEL
    if actor is ActorKind.PROTOCOL:
        return REASON_PROTOCOL_NOT_KERNEL
    if actor is ActorKind.HAMMER or actor is ActorKind.ATP:
        return REASON_HAMMER_CANDIDATE
    if actor is ActorKind.ADVISOR or actor is ActorKind.CANDIDATE:
        return REASON_ADVISOR_CEILING
    return REASON_SCOPED_AUTHORITY


def audit_claim(claim: AuthorityClaim | Mapping[str, Any]) -> AuthorityVerdict:
    """Evaluate one authority claim under the closed boundary rules."""

    if not isinstance(claim, AuthorityClaim):
        if not isinstance(claim, Mapping):
            raise AuthorityAuditError("claim must be AuthorityClaim or mapping")
        claim = AuthorityClaim(
            claim_id=str(claim.get("claim_id") or ""),
            provider_id=str(claim.get("provider_id") or ""),
            actor_kind=str(claim.get("actor_kind") or ActorKind.UNKNOWN.value),
            claimed_authority=str(
                claim.get("claimed_authority") or ClaimedAuthority.NONE.value
            ),
            confidence=claim.get("confidence"),
            is_valid=claim.get("is_valid"),
            similarity=claim.get("similarity"),
            parse_ok=claim.get("parse_ok"),
            status=str(claim.get("status") or ""),
            success=claim.get("success"),
            available=claim.get("available"),
            present=claim.get("present"),
            kernel_accepted=bool(claim.get("kernel_accepted", False)),
            imports=tuple(claim.get("imports") or ()),
            axioms=tuple(claim.get("axioms") or ()),
            environment_id=str(claim.get("environment_id") or ""),
            environment_pinned=bool(claim.get("environment_pinned", False)),
            trust_escapes_rejected=bool(
                claim.get("trust_escapes_rejected", True)
            ),
            independent_reconstruction=bool(
                claim.get("independent_reconstruction", False)
            ),
            notes=str(claim.get("notes") or ""),
            attributes=dict(claim.get("attributes") or {}),
        )

    actor = (
        claim.actor_kind
        if isinstance(claim.actor_kind, ActorKind)
        else classify_actor(claim.provider_id)
    )
    claimed = (
        claim.claimed_authority
        if isinstance(claim.claimed_authority, ClaimedAuthority)
        else ClaimedAuthority(str(claim.claimed_authority))
    )
    reasons: list[str] = []

    # 1) Confidence / is_valid / similarity never prove parse or proof.
    confidence_claim = (
        claim.confidence is not None
        or claim.is_valid is not None
        or claim.similarity is not None
        or claimed is ClaimedAuthority.PARSE_CORRECT
    )
    if confidence_claim:
        proved = confidence_never_proves_parse_correctness(
            confidence=claim.confidence,
            is_valid=claim.is_valid,
            similarity=claim.similarity,
            parse_ok=claim.parse_ok,
        )
        if proved:
            # Unreachable by contract; retained as fail-closed guard.
            reasons.append(REASON_CLAIM_REJECTED)
        reasons.append(REASON_CONFIDENCE_NOT_PROOF)
        if claimed in {
            ClaimedAuthority.PARSE_CORRECT,
            ClaimedAuthority.THEOREM,
            ClaimedAuthority.KERNEL,
        } and actor in {
            ActorKind.ADVISOR,
            ActorKind.CANDIDATE,
            ActorKind.HAMMER,
            ActorKind.UNKNOWN,
        }:
            return AuthorityVerdict(
                claim_id=claim.claim_id,
                provider_id=claim.provider_id,
                actor_kind=actor,
                claimed_authority=claimed,
                disposition=AuditDisposition.REJECT,
                establishes_kernel_authority=False,
                establishes_proof=False,
                is_logic_evidence=False,
                reason_codes=tuple(dict.fromkeys(reasons + [REASON_ADVISOR_CEILING])),
                max_result_authority=ResultAuthority.CANDIDATE,
                notes="Confidence/is_valid never establish parse or proof authority.",
            )

    # 2) Quota / unavailability never become logic evidence.
    if (
        is_quota_or_unavailability_token(claim.status)
        or claim.available is False
        or (
            claim.present is False
            and claimed
            in {
                ClaimedAuthority.THEOREM,
                ClaimedAuthority.KERNEL,
                ClaimedAuthority.SATISFIABILITY,
                ClaimedAuthority.BOUNDED,
                ClaimedAuthority.PROTOCOL,
                ClaimedAuthority.MONITOR,
            }
        )
    ):
        reasons.append(REASON_QUOTA_NOT_LOGIC_EVIDENCE)
        # Explicitly invoke the documented invariant.
        _ = quota_unavailability_never_logic_evidence(
            status=claim.status,
            available=claim.available,
        )
        return AuthorityVerdict(
            claim_id=claim.claim_id,
            provider_id=claim.provider_id,
            actor_kind=actor,
            claimed_authority=claimed,
            disposition=AuditDisposition.INCONCLUSIVE,
            establishes_kernel_authority=False,
            establishes_proof=False,
            is_logic_evidence=False,
            reason_codes=tuple(dict.fromkeys(reasons)),
            max_result_authority=ResultAuthority.CANDIDATE,
            notes="Quota, timeout, and unavailability are operational, not logic evidence.",
        )

    # 3) Generic success never becomes proof.
    generic = is_generic_success_token(claim.status) or claim.success is True
    if generic and claimed in {
        ClaimedAuthority.THEOREM,
        ClaimedAuthority.KERNEL,
        ClaimedAuthority.PARSE_CORRECT,
    }:
        reasons.append(REASON_GENERIC_SUCCESS_NOT_PROOF)
        _ = generic_success_never_becomes_proof(
            status=claim.status,
            success=claim.success,
        )
        # Kernel path may still succeed if official acceptance + pins hold.
        if not (
            actor is ActorKind.KERNEL
            and claim.kernel_accepted
            and establishes_kernel_authority(
                provider_id=claim.provider_id,
                kernel_target=claim.provider_id,
                kernel_accepted=claim.kernel_accepted,
                imports=claim.imports,
                environment_pinned=claim.environment_pinned,
                environment_id=claim.environment_id,
                trust_escapes_rejected=claim.trust_escapes_rejected,
                status="accepted",
                claimed=claimed,
            )
        ):
            return AuthorityVerdict(
                claim_id=claim.claim_id,
                provider_id=claim.provider_id,
                actor_kind=actor,
                claimed_authority=claimed,
                disposition=AuditDisposition.REJECT,
                establishes_kernel_authority=False,
                establishes_proof=False,
                is_logic_evidence=False,
                reason_codes=tuple(
                    dict.fromkeys(reasons + [REASON_CLAIM_REJECTED])
                ),
                max_result_authority=_max_authority_for_actor(actor),
                notes="Generic success tokens never mint theorem/kernel authority.",
            )

    # 4) Presence / usability of non-certifying roles.
    tool_key = claim.provider_id
    if tool_key == "rocq":
        tool_key = "coq"
    if tool_key == "symai":
        tool_key = "symbolicai"
    if tool_key == "tlc":
        tool_key = "tlc"
    try:
        promotion = evaluate_role_aware_promotion(
            tool_key,
            present=bool(claim.present or claim.available),
            usable=bool(claim.available),
            independent_reconstruction=claim.independent_reconstruction,
        )
        if not promotion.can_satisfy_certified_authority and claimed in {
            ClaimedAuthority.THEOREM,
            ClaimedAuthority.KERNEL,
        }:
            reasons.append(REASON_ROLE_CANNOT_CERTIFY)
            if claim.present or claim.available:
                reasons.append(REASON_PRESENCE_NOT_AUTHORITY)
            return AuthorityVerdict(
                claim_id=claim.claim_id,
                provider_id=claim.provider_id,
                actor_kind=actor,
                claimed_authority=claimed,
                disposition=AuditDisposition.REJECT,
                establishes_kernel_authority=False,
                establishes_proof=False,
                is_logic_evidence=False,
                reason_codes=tuple(dict.fromkeys(reasons + list(promotion.reason_codes))),
                max_result_authority=ResultAuthority.CANDIDATE,
                notes="Non-certifying roles cannot satisfy certified authority.",
            )
    except Exception:
        # Unknown tool ids fall through to actor-kind rules.
        pass

    # 5) Official kernel path.
    if claimed in {ClaimedAuthority.KERNEL, ClaimedAuthority.THEOREM}:
        if actor is not ActorKind.KERNEL:
            reasons.append(REASON_KERNEL_REQUIRES_OFFICIAL)
            reasons.append(_scoped_reason(actor))
            return AuthorityVerdict(
                claim_id=claim.claim_id,
                provider_id=claim.provider_id,
                actor_kind=actor,
                claimed_authority=claimed,
                disposition=AuditDisposition.REJECT,
                establishes_kernel_authority=False,
                establishes_proof=False,
                is_logic_evidence=False,
                reason_codes=tuple(dict.fromkeys(reasons)),
                max_result_authority=_max_authority_for_actor(actor),
                notes="Only official kernels may claim theorem/kernel authority.",
            )
        if not claim.kernel_accepted:
            reasons.append(REASON_KERNEL_REQUIRES_ACCEPTANCE)
            return AuthorityVerdict(
                claim_id=claim.claim_id,
                provider_id=claim.provider_id,
                actor_kind=actor,
                claimed_authority=claimed,
                disposition=AuditDisposition.REJECT,
                establishes_kernel_authority=False,
                establishes_proof=False,
                is_logic_evidence=False,
                reason_codes=tuple(dict.fromkeys(reasons)),
                max_result_authority=ResultAuthority.CANDIDATE,
                notes="Kernel authority requires kernel_accepted=True.",
            )
        if not has_pinned_imports(claim.imports, kernel_target=claim.provider_id):
            reasons.append(REASON_KERNEL_REQUIRES_PINNED_IMPORTS)
            return AuthorityVerdict(
                claim_id=claim.claim_id,
                provider_id=claim.provider_id,
                actor_kind=actor,
                claimed_authority=claimed,
                disposition=AuditDisposition.REJECT,
                establishes_kernel_authority=False,
                establishes_proof=False,
                is_logic_evidence=False,
                reason_codes=tuple(dict.fromkeys(reasons)),
                max_result_authority=ResultAuthority.CANDIDATE,
                notes="Kernel authority requires pinned imports.",
            )
        if not claim.environment_pinned and not claim.environment_id:
            reasons.append(REASON_KERNEL_REQUIRES_ENVIRONMENT)
            return AuthorityVerdict(
                claim_id=claim.claim_id,
                provider_id=claim.provider_id,
                actor_kind=actor,
                claimed_authority=claimed,
                disposition=AuditDisposition.REJECT,
                establishes_kernel_authority=False,
                establishes_proof=False,
                is_logic_evidence=False,
                reason_codes=tuple(dict.fromkeys(reasons)),
                max_result_authority=ResultAuthority.CANDIDATE,
                notes="Kernel authority requires a pinned environment identity.",
            )
        if not claim.trust_escapes_rejected:
            reasons.append(REASON_CLAIM_REJECTED)
            return AuthorityVerdict(
                claim_id=claim.claim_id,
                provider_id=claim.provider_id,
                actor_kind=actor,
                claimed_authority=claimed,
                disposition=AuditDisposition.REJECT,
                establishes_kernel_authority=False,
                establishes_proof=False,
                is_logic_evidence=False,
                reason_codes=tuple(dict.fromkeys(reasons)),
                max_result_authority=ResultAuthority.CANDIDATE,
                notes="Trust escapes block kernel authority.",
            )
        ok = establishes_kernel_authority(
            provider_id=claim.provider_id,
            kernel_target=claim.provider_id,
            kernel_accepted=claim.kernel_accepted,
            imports=claim.imports,
            environment_pinned=claim.environment_pinned,
            environment_id=claim.environment_id,
            trust_escapes_rejected=claim.trust_escapes_rejected,
            status=claim.status or "accepted",
            claimed=claimed,
        )
        if ok:
            return AuthorityVerdict(
                claim_id=claim.claim_id,
                provider_id=claim.provider_id,
                actor_kind=actor,
                claimed_authority=claimed,
                disposition=AuditDisposition.KERNEL,
                establishes_kernel_authority=True,
                establishes_proof=True,
                is_logic_evidence=True,
                reason_codes=(REASON_KERNEL_AUTHORITY_ESTABLISHED,),
                max_result_authority=ResultAuthority.THEOREM,
                notes="Official kernel success under pinned imports.",
            )
        reasons.append(REASON_CLAIM_REJECTED)
        return AuthorityVerdict(
            claim_id=claim.claim_id,
            provider_id=claim.provider_id,
            actor_kind=actor,
            claimed_authority=claimed,
            disposition=AuditDisposition.REJECT,
            establishes_kernel_authority=False,
            establishes_proof=False,
            is_logic_evidence=False,
            reason_codes=tuple(dict.fromkeys(reasons)),
            max_result_authority=ResultAuthority.CANDIDATE,
            notes="Kernel claim failed closed authority checks.",
        )

    # 6) Advisor / hammer candidate ceilings.
    if actor in {ActorKind.ADVISOR, ActorKind.CANDIDATE, ActorKind.HAMMER}:
        reasons.append(
            REASON_ADVISOR_CEILING
            if actor is not ActorKind.HAMMER
            else REASON_HAMMER_CANDIDATE
        )
        return AuthorityVerdict(
            claim_id=claim.claim_id,
            provider_id=claim.provider_id,
            actor_kind=actor,
            claimed_authority=claimed,
            disposition=AuditDisposition.SCOPED
            if claimed
            in {ClaimedAuthority.ADVISORY, ClaimedAuthority.CANDIDATE, ClaimedAuthority.NONE}
            else AuditDisposition.REJECT,
            establishes_kernel_authority=False,
            establishes_proof=False,
            is_logic_evidence=False,
            reason_codes=tuple(dict.fromkeys(reasons)),
            max_result_authority=ResultAuthority.CANDIDATE,
            notes=f"Authority ceiling remains {UNVERIFIED_AUTHORITY}.",
        )

    # 7) Scoped non-kernel authorities (solver, model checker, protocol, monitor).
    if actor in {
        ActorKind.SOLVER,
        ActorKind.ATP,
        ActorKind.MODEL_CHECKER,
        ActorKind.PROTOCOL,
        ActorKind.MONITOR,
    }:
        allowed_claims = {
            ActorKind.SOLVER: {
                ClaimedAuthority.SATISFIABILITY,
                ClaimedAuthority.NONE,
            },
            ActorKind.ATP: {
                ClaimedAuthority.RECONSTRUCTION,
                ClaimedAuthority.CANDIDATE,
                ClaimedAuthority.NONE,
            },
            ActorKind.MODEL_CHECKER: {
                ClaimedAuthority.BOUNDED,
                ClaimedAuthority.NONE,
            },
            ActorKind.PROTOCOL: {
                ClaimedAuthority.PROTOCOL,
                ClaimedAuthority.NONE,
            },
            ActorKind.MONITOR: {
                ClaimedAuthority.MONITOR,
                ClaimedAuthority.NONE,
            },
        }[actor]
        if claimed in allowed_claims:
            reasons.append(REASON_SCOPED_AUTHORITY)
            reasons.append(_scoped_reason(actor))
            return AuthorityVerdict(
                claim_id=claim.claim_id,
                provider_id=claim.provider_id,
                actor_kind=actor,
                claimed_authority=claimed,
                disposition=AuditDisposition.SCOPED,
                establishes_kernel_authority=False,
                establishes_proof=False,
                is_logic_evidence=claimed is not ClaimedAuthority.NONE,
                reason_codes=tuple(dict.fromkeys(reasons)),
                max_result_authority=_max_authority_for_actor(actor),
                notes="Scoped authority is non-interchangeable with kernel proof.",
            )
        reasons.append(_scoped_reason(actor))
        reasons.append(REASON_CLAIM_REJECTED)
        return AuthorityVerdict(
            claim_id=claim.claim_id,
            provider_id=claim.provider_id,
            actor_kind=actor,
            claimed_authority=claimed,
            disposition=AuditDisposition.REJECT,
            establishes_kernel_authority=False,
            establishes_proof=False,
            is_logic_evidence=False,
            reason_codes=tuple(dict.fromkeys(reasons)),
            max_result_authority=_max_authority_for_actor(actor),
            notes="Claimed authority exceeds the actor's closed ceiling.",
        )

    # Default fail-closed.
    reasons.append(REASON_CLAIM_REJECTED)
    return AuthorityVerdict(
        claim_id=claim.claim_id,
        provider_id=claim.provider_id,
        actor_kind=actor,
        claimed_authority=claimed,
        disposition=AuditDisposition.REJECT,
        establishes_kernel_authority=False,
        establishes_proof=False,
        is_logic_evidence=False,
        reason_codes=tuple(dict.fromkeys(reasons)),
        max_result_authority=ResultAuthority.CANDIDATE,
        notes="Unrecognized actor/claim pair rejected.",
    )


def build_adversarial_claim_corpus() -> tuple[AuthorityClaim, ...]:
    """Closed adversarial + honest claim corpus for LFP-042 evidence."""

    lean_imports = DEFAULT_LEAN_IMPORTS
    claims: list[AuthorityClaim] = [
        # --- Advisors: confidence never proves ---
        AuthorityClaim(
            claim_id="symai.confidence_parse_proof",
            provider_id="symbolicai",
            actor_kind=ActorKind.ADVISOR,
            claimed_authority=ClaimedAuthority.PARSE_CORRECT,
            confidence=0.999,
            is_valid=True,
            parse_ok=True,
            notes="High SymAI confidence must not prove parse correctness.",
        ),
        AuthorityClaim(
            claim_id="symai.confidence_theorem",
            provider_id="symai",
            actor_kind=ActorKind.ADVISOR,
            claimed_authority=ClaimedAuthority.THEOREM,
            confidence=1.0,
            is_valid=True,
            similarity=1.0,
            status="success",
            notes="SymAI confidence must not mint theorem authority.",
        ),
        AuthorityClaim(
            claim_id="ergoai.availability_kernel",
            provider_id="ergoai",
            actor_kind=ActorKind.ADVISOR,
            claimed_authority=ClaimedAuthority.KERNEL,
            available=True,
            present=True,
            status="ok",
            notes="ErgoAI availability must not establish kernel authority.",
        ),
        AuthorityClaim(
            claim_id="ergoai.candidate_only",
            provider_id="ergoai",
            actor_kind=ActorKind.ADVISOR,
            claimed_authority=ClaimedAuthority.CANDIDATE,
            confidence=0.5,
            notes="Honest ErgoAI candidate claim stays advisory.",
        ),
        # --- Hammer / premise ---
        AuthorityClaim(
            claim_id="hammer.premise_theorem",
            provider_id="hammer",
            actor_kind=ActorKind.HAMMER,
            claimed_authority=ClaimedAuthority.THEOREM,
            status="proved",
            success=True,
            notes="Hammer premise/solver success remains candidate until reconstruction.",
            attributes={"stage": "premise"},
        ),
        AuthorityClaim(
            claim_id="hammer.candidate_honest",
            provider_id="hammer",
            actor_kind=ActorKind.HAMMER,
            claimed_authority=ClaimedAuthority.CANDIDATE,
            status="candidate",
            notes="Honest hammer candidate posture.",
        ),
        # --- Solvers ---
        AuthorityClaim(
            claim_id="z3.generic_success_kernel",
            provider_id="z3",
            actor_kind=ActorKind.SOLVER,
            claimed_authority=ClaimedAuthority.KERNEL,
            status="success",
            success=True,
            notes="Z3 generic success must not become kernel proof.",
        ),
        AuthorityClaim(
            claim_id="z3.sat_scoped",
            provider_id="z3",
            actor_kind=ActorKind.SOLVER,
            claimed_authority=ClaimedAuthority.SATISFIABILITY,
            status="unsat",
            notes="Z3 may hold satisfiability authority only.",
        ),
        AuthorityClaim(
            claim_id="cvc5.quota_not_evidence",
            provider_id="cvc5",
            actor_kind=ActorKind.SOLVER,
            claimed_authority=ClaimedAuthority.SATISFIABILITY,
            status="quota_exceeded",
            notes="Solver quota exhaustion is not logic evidence.",
        ),
        # --- ATP ---
        AuthorityClaim(
            claim_id="vampire.proved_not_kernel",
            provider_id="vampire",
            actor_kind=ActorKind.ATP,
            claimed_authority=ClaimedAuthority.KERNEL,
            status="proved",
            success=True,
            notes="ATP proved remains reconstruction/candidate until kernel.",
        ),
        AuthorityClaim(
            claim_id="eprover.reconstruction_scoped",
            provider_id="eprover",
            actor_kind=ActorKind.ATP,
            claimed_authority=ClaimedAuthority.RECONSTRUCTION,
            status="proved",
            notes="ATP reconstruction-scoped authority.",
        ),
        # --- Model checkers ---
        AuthorityClaim(
            claim_id="tlc.bounded_not_kernel",
            provider_id="tla_tlc",
            actor_kind=ActorKind.MODEL_CHECKER,
            claimed_authority=ClaimedAuthority.KERNEL,
            status="success",
            notes="Bounded model check never yields kernel authority.",
        ),
        AuthorityClaim(
            claim_id="apalache.bounded_scoped",
            provider_id="apalache",
            actor_kind=ActorKind.MODEL_CHECKER,
            claimed_authority=ClaimedAuthority.BOUNDED,
            status="satisfied",
            notes="Apalache bounded authority is scoped.",
        ),
        # --- Protocol ---
        AuthorityClaim(
            claim_id="proverif.protocol_not_kernel",
            provider_id="proverif",
            actor_kind=ActorKind.PROTOCOL,
            claimed_authority=ClaimedAuthority.THEOREM,
            status="secure",
            notes="Protocol secure is not theorem authority.",
        ),
        AuthorityClaim(
            claim_id="tamarin.protocol_scoped",
            provider_id="tamarin",
            actor_kind=ActorKind.PROTOCOL,
            claimed_authority=ClaimedAuthority.PROTOCOL,
            status="secure",
            notes="Tamarin protocol authority is scoped.",
        ),
        # --- Monitor ---
        AuthorityClaim(
            claim_id="runtime_mtl.monitor_not_kernel",
            provider_id="runtime_mtl",
            actor_kind=ActorKind.MONITOR,
            claimed_authority=ClaimedAuthority.KERNEL,
            status="satisfied",
            notes="Finite-trace monitor never yields kernel authority.",
        ),
        AuthorityClaim(
            claim_id="runtime_mtl.monitor_scoped",
            provider_id="runtime_mtl",
            actor_kind=ActorKind.MONITOR,
            claimed_authority=ClaimedAuthority.MONITOR,
            status="satisfied",
            notes="Runtime MTL finite-trace authority is scoped.",
        ),
        # --- Unavailability ---
        AuthorityClaim(
            claim_id="lean.unavailable_not_evidence",
            provider_id="lean",
            actor_kind=ActorKind.KERNEL,
            claimed_authority=ClaimedAuthority.KERNEL,
            status="unavailable",
            available=False,
            notes="Kernel unavailability is not logic evidence.",
        ),
        AuthorityClaim(
            claim_id="isabelle.timeout_not_evidence",
            provider_id="isabelle",
            actor_kind=ActorKind.KERNEL,
            claimed_authority=ClaimedAuthority.THEOREM,
            status="timeout",
            notes="Kernel timeout is not logic evidence.",
        ),
        # --- Kernel incomplete pins ---
        AuthorityClaim(
            claim_id="lean.accepted_without_imports",
            provider_id="lean",
            actor_kind=ActorKind.KERNEL,
            claimed_authority=ClaimedAuthority.KERNEL,
            kernel_accepted=True,
            environment_pinned=True,
            environment_id="env:lean:missing-imports",
            imports=(),
            notes="Kernel acceptance without pinned imports fails closed.",
        ),
        AuthorityClaim(
            claim_id="rocq.accepted_without_environment",
            provider_id="rocq",
            actor_kind=ActorKind.KERNEL,
            claimed_authority=ClaimedAuthority.THEOREM,
            kernel_accepted=True,
            imports=DEFAULT_ROCQ_IMPORTS,
            environment_pinned=False,
            environment_id="",
            notes="Kernel acceptance without environment pin fails closed.",
        ),
        # --- Honest official kernel success ---
        AuthorityClaim(
            claim_id="lean.official_kernel_success",
            provider_id="lean",
            actor_kind=ActorKind.KERNEL,
            claimed_authority=ClaimedAuthority.KERNEL,
            kernel_accepted=True,
            imports=lean_imports,
            environment_pinned=True,
            environment_id="env:lean:pinned-1",
            trust_escapes_rejected=True,
            status="accepted",
            axioms=("classical",),
            notes="Official Lean success under pinned imports establishes kernel authority.",
        ),
        AuthorityClaim(
            claim_id="isabelle.official_kernel_success",
            provider_id="isabelle",
            actor_kind=ActorKind.KERNEL,
            claimed_authority=ClaimedAuthority.THEOREM,
            kernel_accepted=True,
            imports=DEFAULT_ISABELLE_IMPORTS,
            environment_pinned=True,
            environment_id="env:isabelle:pinned-1",
            trust_escapes_rejected=True,
            status="accepted",
            notes="Official Isabelle success under pinned imports establishes theorem authority.",
        ),
        AuthorityClaim(
            claim_id="rocq.official_kernel_success",
            provider_id="rocq",
            actor_kind=ActorKind.KERNEL,
            claimed_authority=ClaimedAuthority.KERNEL,
            kernel_accepted=True,
            imports=DEFAULT_ROCQ_IMPORTS,
            environment_id="env:rocq:pinned-1",
            environment_pinned=True,
            trust_escapes_rejected=True,
            status="accepted",
            notes="Official Rocq success under pinned imports establishes kernel authority.",
        ),
    ]
    return tuple(claims)


@dataclass(frozen=True, slots=True)
class LogicAuthorityAuditReport:
    """Deterministic ``LogicAuthorityAudit@1`` envelope."""

    verdicts: tuple[AuthorityVerdict, ...]
    claims: tuple[AuthorityClaim, ...]
    summary: Mapping[str, Any] = field(default_factory=dict)
    evidence_subset: tuple[str, ...] = REQUIRED_EVIDENCE_SUBSET
    schema_version: str = LOGIC_AUTHORITY_AUDIT_REPORT_SCHEMA
    interface: str = LOGIC_AUTHORITY_AUDIT_INTERFACE
    report_version: str = AUDIT_REPORT_VERSION
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID
    program_id: str = PROGRAM_ID

    def __post_init__(self) -> None:
        object.__setattr__(self, "verdicts", tuple(self.verdicts))
        object.__setattr__(self, "claims", tuple(self.claims))
        if len(self.verdicts) != len(self.claims):
            raise AuthorityAuditError(
                "verdicts and claims must be the same length"
            )
        object.__setattr__(
            self,
            "evidence_subset",
            tuple(_text(item, "evidence_subset item") for item in self.evidence_subset),
        )
        if not isinstance(self.summary, Mapping):
            raise AuthorityAuditError("summary must be a mapping")
        object.__setattr__(
            self, "summary", MappingProxyType(dict(self.summary))
        )
        if self.interface != LOGIC_AUTHORITY_AUDIT_INTERFACE:
            raise AuthorityAuditError(
                f"interface must be {LOGIC_AUTHORITY_AUDIT_INTERFACE}"
            )
        if self.schema_version != LOGIC_AUTHORITY_AUDIT_REPORT_SCHEMA:
            raise AuthorityAuditError(
                f"report schema must be {LOGIC_AUTHORITY_AUDIT_REPORT_SCHEMA}"
            )

    @property
    def digest(self) -> str:
        return _stable_digest(self.to_dict())

    @property
    def all_boundaries_hold(self) -> bool:
        return bool(self.summary.get("all_boundaries_hold"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [item.to_dict() for item in self.claims],
            "evidence_subset": list(self.evidence_subset),
            "goal_id": self.goal_id,
            "interface": self.interface,
            "program_id": self.program_id,
            "report_version": self.report_version,
            "schema_version": self.schema_version,
            "summary": dict(self.summary),
            "task_id": self.task_id,
            "verdicts": [item.to_dict() for item in self.verdicts],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        separators = None if indent is not None else (",", ":")
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            indent=indent,
            separators=separators,
            sort_keys=True,
        ) + ("\n" if indent is not None else "")


@dataclass(frozen=True, slots=True)
class LogicAuthorityAudit:
    """``LogicAuthorityAudit@1`` evaluator."""

    interface: str = LOGIC_AUTHORITY_AUDIT_INTERFACE
    schema_version: str = LOGIC_AUTHORITY_AUDIT_SCHEMA
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID

    def __post_init__(self) -> None:
        if self.interface != LOGIC_AUTHORITY_AUDIT_INTERFACE:
            raise AuthorityAuditError(
                f"interface must be {LOGIC_AUTHORITY_AUDIT_INTERFACE}"
            )
        if self.schema_version != LOGIC_AUTHORITY_AUDIT_SCHEMA:
            raise AuthorityAuditError(
                f"schema must be {LOGIC_AUTHORITY_AUDIT_SCHEMA}"
            )

    def audit(
        self,
        claims: Sequence[AuthorityClaim | Mapping[str, Any]] | None = None,
    ) -> LogicAuthorityAuditReport:
        corpus = (
            tuple(
                item
                if isinstance(item, AuthorityClaim)
                else AuthorityClaim(
                    claim_id=str(item.get("claim_id") or ""),
                    provider_id=str(item.get("provider_id") or ""),
                    actor_kind=str(
                        item.get("actor_kind") or ActorKind.UNKNOWN.value
                    ),
                    claimed_authority=str(
                        item.get("claimed_authority")
                        or ClaimedAuthority.NONE.value
                    ),
                    confidence=item.get("confidence"),
                    is_valid=item.get("is_valid"),
                    similarity=item.get("similarity"),
                    parse_ok=item.get("parse_ok"),
                    status=str(item.get("status") or ""),
                    success=item.get("success"),
                    available=item.get("available"),
                    present=item.get("present"),
                    kernel_accepted=bool(item.get("kernel_accepted", False)),
                    imports=tuple(item.get("imports") or ()),
                    axioms=tuple(item.get("axioms") or ()),
                    environment_id=str(item.get("environment_id") or ""),
                    environment_pinned=bool(
                        item.get("environment_pinned", False)
                    ),
                    trust_escapes_rejected=bool(
                        item.get("trust_escapes_rejected", True)
                    ),
                    independent_reconstruction=bool(
                        item.get("independent_reconstruction", False)
                    ),
                    notes=str(item.get("notes") or ""),
                    attributes=dict(item.get("attributes") or {}),
                )
                for item in claims
            )
            if claims is not None
            else build_adversarial_claim_corpus()
        )
        verdicts = tuple(audit_claim(item) for item in corpus)
        return _build_report(corpus, verdicts)

    def to_dict(self) -> dict[str, str]:
        return {
            "goal_id": self.goal_id,
            "interface": self.interface,
            "schema_version": self.schema_version,
            "task_id": self.task_id,
        }


def _build_report(
    claims: Sequence[AuthorityClaim],
    verdicts: Sequence[AuthorityVerdict],
) -> LogicAuthorityAuditReport:
    kernel_ok = [
        v for v in verdicts if v.establishes_kernel_authority
    ]
    rejected = [v for v in verdicts if v.disposition is AuditDisposition.REJECT]
    inconclusive = [
        v for v in verdicts if v.disposition is AuditDisposition.INCONCLUSIVE
    ]
    scoped = [v for v in verdicts if v.disposition is AuditDisposition.SCOPED]

    # Boundary invariants that must hold for the default corpus.
    confidence_blocked = all(
        (not v.establishes_proof)
        for c, v in zip(claims, verdicts)
        if c.confidence is not None
        or c.is_valid is not None
        or c.similarity is not None
        or c.claimed_authority is ClaimedAuthority.PARSE_CORRECT
    )
    generic_blocked = all(
        (not v.establishes_kernel_authority)
        for c, v in zip(claims, verdicts)
        if (
            is_generic_success_token(c.status) or c.success is True
        )
        and c.actor_kind is not ActorKind.KERNEL
    )
    quota_blocked = all(
        (not v.is_logic_evidence)
        for c, v in zip(claims, verdicts)
        if is_quota_or_unavailability_token(c.status) or c.available is False
    )
    kernel_only_official = all(
        v.provider_id in _KERNEL_PROVIDER_IDS
        or v.provider_id == "coq"
        for v in kernel_ok
    )
    kernel_has_pins = all(
        has_pinned_imports(
            next(c.imports for c in claims if c.claim_id == v.claim_id),
            kernel_target=v.provider_id,
        )
        for v in kernel_ok
    )

    # Surface / role cross-checks (pure).
    surface_roles = {
        surface.value: surface_authority_role(surface).value
        for surface in RouteSurface
    }
    non_kernel_surfaces_block_theorem = all(
        result_authority_for_surface(surface) is not ResultAuthority.THEOREM
        for surface in RouteSurface
        if surface is not RouteSurface.KERNEL_NATIVE
    )

    advisor_tools_blocked = all(
        not can_satisfy_certified_authority_requirement(tool_id)
        for tool_id in ("symbolicai", "ergoai", "leanstral", "autoencoder", "hammer")
    )

    all_boundaries_hold = all(
        (
            confidence_blocked,
            generic_blocked,
            quota_blocked,
            kernel_only_official,
            kernel_has_pins,
            non_kernel_surfaces_block_theorem,
            advisor_tools_blocked,
            bool(kernel_ok),  # corpus must include at least one honest kernel success
        )
    )

    summary = {
        "all_boundaries_hold": all_boundaries_hold,
        "advisor_tools_blocked_from_certified_authority": advisor_tools_blocked,
        "claim_count": len(claims),
        "confidence_never_proves_parse_correctness": confidence_blocked,
        "generic_success_never_becomes_proof": generic_blocked,
        "inconclusive_count": len(inconclusive),
        "kernel_authority_count": len(kernel_ok),
        "kernel_authority_only_official_under_pinned_imports": (
            kernel_only_official and kernel_has_pins
        ),
        "kernel_native_surface_role": surface_roles.get(
            RouteSurface.KERNEL_NATIVE.value
        ),
        "non_kernel_surfaces_block_theorem": non_kernel_surfaces_block_theorem,
        "quota_unavailability_never_logic_evidence": quota_blocked,
        "rejected_count": len(rejected),
        "scoped_count": len(scoped),
        "surface_authority_roles": surface_roles,
        "unverified_authority_token": UNVERIFIED_AUTHORITY,
        "verdict_count": len(verdicts),
    }
    return LogicAuthorityAuditReport(
        verdicts=tuple(verdicts),
        claims=tuple(claims),
        summary=summary,
        evidence_subset=REQUIRED_EVIDENCE_SUBSET,
    )


def run_authority_audit(
    claims: Sequence[AuthorityClaim | Mapping[str, Any]] | None = None,
) -> LogicAuthorityAuditReport:
    """Run the default or supplied claim corpus through ``LogicAuthorityAudit@1``."""

    return LogicAuthorityAudit().audit(claims)


DEFAULT_AUTHORITY_AUDIT: Final = LogicAuthorityAudit()


__all__ = [
    "AUDIT_REPORT_VERSION",
    "ActorKind",
    "AuditDisposition",
    "AuthorityAuditError",
    "AuthorityClaim",
    "AuthorityVerdict",
    "ClaimedAuthority",
    "DEFAULT_AUTHORITY_AUDIT",
    "GOAL_ID",
    "LOGIC_AUTHORITY_AUDIT_INTERFACE",
    "LOGIC_AUTHORITY_AUDIT_REPORT_SCHEMA",
    "LOGIC_AUTHORITY_AUDIT_SCHEMA",
    "LOGIC_AUTHORITY_CLAIM_SCHEMA",
    "LOGIC_AUTHORITY_VERDICT_SCHEMA",
    "LogicAuthorityAudit",
    "LogicAuthorityAuditReport",
    "PROGRAM_ID",
    "REASON_ADVISOR_CEILING",
    "REASON_BOUNDED_NOT_KERNEL",
    "REASON_CLAIM_REJECTED",
    "REASON_CONFIDENCE_NOT_PROOF",
    "REASON_GENERIC_SUCCESS_NOT_PROOF",
    "REASON_HAMMER_CANDIDATE",
    "REASON_KERNEL_AUTHORITY_ESTABLISHED",
    "REASON_KERNEL_REQUIRES_ACCEPTANCE",
    "REASON_KERNEL_REQUIRES_ENVIRONMENT",
    "REASON_KERNEL_REQUIRES_OFFICIAL",
    "REASON_KERNEL_REQUIRES_PINNED_IMPORTS",
    "REASON_MONITOR_NOT_KERNEL",
    "REASON_PRESENCE_NOT_AUTHORITY",
    "REASON_PROTOCOL_NOT_KERNEL",
    "REASON_QUOTA_NOT_LOGIC_EVIDENCE",
    "REASON_ROLE_CANNOT_CERTIFY",
    "REASON_SCOPED_AUTHORITY",
    "REASON_SOLVER_NOT_KERNEL",
    "REQUIRED_EVIDENCE_SUBSET",
    "TASK_ID",
    "audit_claim",
    "build_adversarial_claim_corpus",
    "classify_actor",
    "confidence_never_proves_parse_correctness",
    "establishes_kernel_authority",
    "generic_success_never_becomes_proof",
    "has_pinned_imports",
    "is_generic_success_token",
    "is_quota_or_unavailability_token",
    "matrix_authority_ceiling",
    "quota_unavailability_never_logic_evidence",
    "run_authority_audit",
]
