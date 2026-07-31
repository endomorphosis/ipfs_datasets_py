"""Authorization obligation composition and decision policy (LIG-033).

Interfaces:

* ``AuthorizationQueryComposer@1`` — emit per-action/effect proof jobs that
  preserve native logic families and typed cross-view links.
* ``AuthorizationDecisionPolicy@1`` — closed-world deny-overrides combining
  that requires an applicable positive grant **and** a proved non-conflict
  obligation (not merely the absence of a retrieved deny).
* ``AuthorizationDecision@1`` — internal multi-status decision that maps to
  the legacy allow/reject/abstain wire contract without reverse inference.

Composition is pure: it never installs solvers, mutates a corpus, or executes
source instructions.  Portfolio execution of the emitted jobs lives in
:mod:`.portfolio`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ..formalization.constraint_contracts import (
    ConstraintArtifact,
    ConstraintRole,
    NativeViewBinding,
    WorldPolicyKind,
    forbid_silent_logic_concatenation,
)
from ..formalization.views import CrossViewLink
from ..ir_core.claims import FrozenMap, stable_digest
from ..ir_core.protocols import AuthorityKind, QueryKind
from .profiles import (
    AdmissibilityProfile,
    AdmissibilityProfileId,
    resolve_profile_fail_closed,
)
from .reasons import (
    AdmissibilityReason,
    AdmissibilityReasonCode,
    AdmissibilityStatus,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

AUTHORIZATION_QUERY_COMPOSER_INTERFACE: Final = "AuthorizationQueryComposer@1"
AUTHORIZATION_QUERY_COMPOSER_SCHEMA_VERSION: Final = (
    "authorization-query-composer/v1"
)
AUTHORIZATION_DECISION_POLICY_INTERFACE: Final = "AuthorizationDecisionPolicy@1"
AUTHORIZATION_DECISION_POLICY_SCHEMA_VERSION: Final = (
    "authorization-decision-policy/v1"
)
AUTHORIZATION_DECISION_INTERFACE: Final = "AuthorizationDecision@1"
AUTHORIZATION_DECISION_SCHEMA_VERSION: Final = "authorization-decision/v1"
AUTHORIZATION_QUERY_BUNDLE_SCHEMA_VERSION: Final = "authorization-query-bundle/v1"
PROOF_JOB_SCHEMA_VERSION: Final = "authorization-proof-job/v1"
JOB_RESULT_SCHEMA_VERSION: Final = "authorization-job-result/v1"
ACTION_SCOPE_SCHEMA_VERSION: Final = "authorization-action-scope/v1"

MAX_ACTIONS: Final = 256
MAX_JOBS_PER_ACTION: Final = 64
MAX_IDENTIFIER_CHARS: Final = 256
MAX_REASON_CHARS: Final = 512

# Paths / result authorities that can never authorize an allow.
NON_ALLOWING_AUTHORITY_PATHS: Final[frozenset[str]] = frozenset(
    {
        "unsupported",
        "unknown",
        "contradictory",
        "unavailable",
        "sat_only",
        "satisfiability",
        "model",
        "monitor",
        "runtime_monitor",
        "evidence",
        "evidence_readiness",
        "policy",
        "policy_approval",
        "simulation",
        "simulated",
    }
)


class ComposeError(ValueError):
    """Raised when composition or decision policy fails closed."""


class ProofJobKind(str, Enum):
    """Closed set of proof jobs emitted for each action/effect."""

    APPLICABILITY = "applicability"
    POSITIVE_GRANT = "positive_grant"
    NON_CONFLICT = "non_conflict"
    SECURITY_INVARIANT = "security_invariant"
    OBLIGATION_PRE = "obligation_pre"
    OBLIGATION_DURING = "obligation_during"
    OBLIGATION_POST = "obligation_post"
    CONSISTENCY = "consistency"
    TRANSLATION = "translation"
    RECONSTRUCTION = "reconstruction"
    COVERAGE = "coverage"
    CONTEXT_BINDING = "context_binding"


# Mandatory job kinds for every closed-world action evaluation.
CLOSED_PROFILE_REQUIRED_JOBS: Final[tuple[ProofJobKind, ...]] = (
    ProofJobKind.APPLICABILITY,
    ProofJobKind.POSITIVE_GRANT,
    ProofJobKind.NON_CONFLICT,
    ProofJobKind.SECURITY_INVARIANT,
    ProofJobKind.OBLIGATION_PRE,
    ProofJobKind.COVERAGE,
    ProofJobKind.CONTEXT_BINDING,
)


class InternalDecisionStatus(str, Enum):
    """Internal multi-status decision before wire compatibility mapping."""

    ALLOW = "allow"
    DENY = "deny"
    REVIEW = "review"
    INDETERMINATE = "indeterminate"
    ERROR = "error"


class JobVerdict(str, Enum):
    """Normalized per-job outcome used by the decision policy."""

    PROVED = "proved"
    DISPROVED = "disproved"
    DENIED = "denied"
    REVIEW = "review"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    CONTRADICTORY = "contradictory"
    TIMEOUT = "timeout"
    ERROR = "error"
    # Explicit non-authority paths that must never become allow.
    SAT_ONLY = "sat_only"
    MODEL = "model"
    MONITOR = "monitor"
    EVIDENCE = "evidence"
    POLICY = "policy"
    SIMULATION = "simulation"


class CombiningRule(str, Enum):
    """How multi-job / multi-backend results combine."""

    DENY_OVERRIDES = "deny_overrides"
    FAIL_CLOSED = "fail_closed"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ComposeError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise ComposeError(f"{name} must be a non-empty trimmed string")
    if len(value) > MAX_IDENTIFIER_CHARS and name.endswith(
        ("_id", "id", "action", "effect", "domain", "logic_family")
    ):
        raise ComposeError(f"{name} exceeds maximum length")
    return value


def _optional_text(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name)


def _digest(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ComposeError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _optional_digest(value: Any, name: str) -> str:
    if value in (None, ""):
        return ""
    return _digest(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ComposeError(f"{name} must be one of: {allowed}") from exc


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ComposeError(f"{name} must be a mapping")
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ComposeError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def _unique_sorted_ids(values: Any, name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(
        values, Sequence
    ):
        raise ComposeError(f"{name} must be a sequence of strings")
    items = tuple(_text(item, f"{name} item") for item in values)
    if len(items) != len(set(items)):
        raise ComposeError(f"{name} must be unique")
    return tuple(sorted(items))


def _sha256_hex(payload: Mapping[str, Any] | str | bytes) -> str:
    if isinstance(payload, (str, bytes)):
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
    else:
        data = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Action scope and proof jobs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActionScope:
    """One requested action or effect that must be authorized."""

    action_id: str
    effect_id: str = ""
    resource_ids: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()
    domain: str = "intent"
    logic_family: str = "first_order"
    statement: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = ACTION_SCOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "action_id", _text(self.action_id, "action_id")
        )
        object.__setattr__(
            self, "effect_id", _optional_text(self.effect_id, "effect_id")
        )
        object.__setattr__(
            self,
            "resource_ids",
            _unique_sorted_ids(self.resource_ids, "resource_ids"),
        )
        object.__setattr__(
            self,
            "capability_ids",
            _unique_sorted_ids(self.capability_ids, "capability_ids"),
        )
        object.__setattr__(self, "domain", _text(self.domain, "domain"))
        object.__setattr__(
            self, "logic_family", _text(self.logic_family, "logic_family")
        )
        if not isinstance(self.statement, str):
            raise ComposeError("statement must be a string")
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != ACTION_SCOPE_SCHEMA_VERSION:
            raise ComposeError(
                f"unsupported action scope schema: {self.schema_version!r}"
            )

    @property
    def scope_key(self) -> str:
        effect = self.effect_id or self.action_id
        return f"{self.action_id}::{effect}"

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "capability_ids": list(self.capability_ids),
            "domain": self.domain,
            "effect_id": self.effect_id,
            "logic_family": self.logic_family,
            "metadata": self.metadata.to_dict(),
            "resource_ids": list(self.resource_ids),
            "schema_version": self.schema_version,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ActionScope":
        value = _mapping(value, "action scope")
        _reject_unknown(
            value,
            frozenset(
                {
                    "action_id",
                    "capability_ids",
                    "domain",
                    "effect_id",
                    "logic_family",
                    "metadata",
                    "resource_ids",
                    "schema_version",
                    "statement",
                }
            ),
            "action scope",
        )
        return cls(
            action_id=value.get("action_id", ""),
            effect_id=value.get("effect_id", ""),
            resource_ids=tuple(value.get("resource_ids", ())),
            capability_ids=tuple(value.get("capability_ids", ())),
            domain=value.get("domain", "intent"),
            logic_family=value.get("logic_family", "first_order"),
            statement=value.get("statement", ""),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get(
                "schema_version", ACTION_SCOPE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ProofJob:
    """One typed proof obligation for a single action/effect scope.

    Native logic is preserved: a job binds exactly one ``logic_family`` and
    optional typed cross-view link identities.  Jobs are never concatenated
    across logic families into an unsound mega-formula.
    """

    job_id: str
    kind: ProofJobKind
    action_id: str
    effect_id: str
    logic_family: str
    domain: str
    query_kind: QueryKind
    required_authority: AuthorityKind
    statement: str = ""
    constraint_roles: tuple[str, ...] = ()
    view_ids: tuple[str, ...] = ()
    cross_view_link_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    evidence_cids: tuple[str, ...] = ()
    world_policy: WorldPolicyKind = WorldPolicyKind.CLOSED
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = PROOF_JOB_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _text(self.job_id, "job_id"))
        object.__setattr__(self, "kind", _enum(self.kind, ProofJobKind, "kind"))
        object.__setattr__(
            self, "action_id", _text(self.action_id, "action_id")
        )
        object.__setattr__(
            self, "effect_id", _optional_text(self.effect_id, "effect_id")
        )
        object.__setattr__(
            self, "logic_family", _text(self.logic_family, "logic_family")
        )
        object.__setattr__(self, "domain", _text(self.domain, "domain"))
        object.__setattr__(
            self, "query_kind", _enum(self.query_kind, QueryKind, "query_kind")
        )
        object.__setattr__(
            self,
            "required_authority",
            _enum(
                self.required_authority, AuthorityKind, "required_authority"
            ),
        )
        # Authority must match the question asked.
        if self.query_kind.authority_kind is not self.required_authority:
            raise ComposeError(
                "proof job query_kind authority must match required_authority"
            )
        if not isinstance(self.statement, str):
            raise ComposeError("statement must be a string")
        object.__setattr__(
            self,
            "constraint_roles",
            _unique_sorted_ids(self.constraint_roles, "constraint_roles"),
        )
        object.__setattr__(
            self, "view_ids", _unique_sorted_ids(self.view_ids, "view_ids")
        )
        object.__setattr__(
            self,
            "cross_view_link_ids",
            _unique_sorted_ids(
                self.cross_view_link_ids, "cross_view_link_ids"
            ),
        )
        object.__setattr__(
            self,
            "assumption_ids",
            _unique_sorted_ids(self.assumption_ids, "assumption_ids"),
        )
        object.__setattr__(
            self,
            "evidence_cids",
            _unique_sorted_ids(self.evidence_cids, "evidence_cids"),
        )
        object.__setattr__(
            self,
            "world_policy",
            _enum(self.world_policy, WorldPolicyKind, "world_policy"),
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_JOB_SCHEMA_VERSION:
            raise ComposeError(
                f"unsupported proof job schema: {self.schema_version!r}"
            )
        forbid_silent_logic_concatenation(
            (self.logic_family,),
            context=f"proof job {self.job_id!r}",
        )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "assumption_ids": list(self.assumption_ids),
            "constraint_roles": list(self.constraint_roles),
            "cross_view_link_ids": list(self.cross_view_link_ids),
            "domain": self.domain,
            "effect_id": self.effect_id,
            "evidence_cids": list(self.evidence_cids),
            "job_id": self.job_id,
            "kind": self.kind.value,
            "logic_family": self.logic_family,
            "metadata": self.metadata.to_dict(),
            "query_kind": self.query_kind.value,
            "required_authority": self.required_authority.value,
            "schema_version": self.schema_version,
            "statement": self.statement,
            "view_ids": list(self.view_ids),
            "world_policy": self.world_policy.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofJob":
        value = _mapping(value, "proof job")
        _reject_unknown(
            value,
            frozenset(
                {
                    "action_id",
                    "assumption_ids",
                    "constraint_roles",
                    "cross_view_link_ids",
                    "domain",
                    "effect_id",
                    "evidence_cids",
                    "job_id",
                    "kind",
                    "logic_family",
                    "metadata",
                    "query_kind",
                    "required_authority",
                    "schema_version",
                    "statement",
                    "view_ids",
                    "world_policy",
                }
            ),
            "proof job",
        )
        return cls(
            job_id=value.get("job_id", ""),
            kind=value.get("kind", ""),
            action_id=value.get("action_id", ""),
            effect_id=value.get("effect_id", ""),
            logic_family=value.get("logic_family", ""),
            domain=value.get("domain", ""),
            query_kind=value.get("query_kind", ""),
            required_authority=value.get("required_authority", ""),
            statement=value.get("statement", ""),
            constraint_roles=tuple(value.get("constraint_roles", ())),
            view_ids=tuple(value.get("view_ids", ())),
            cross_view_link_ids=tuple(value.get("cross_view_link_ids", ())),
            assumption_ids=tuple(value.get("assumption_ids", ())),
            evidence_cids=tuple(value.get("evidence_cids", ())),
            world_policy=value.get("world_policy", WorldPolicyKind.CLOSED),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get(
                "schema_version", PROOF_JOB_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationQueryBundle:
    """``AuthorizationQueryBundle@1`` — composed proof jobs for one evaluation.

    Holds the exact evaluation context, approved profile, corpus roots, and
    the ordered (deterministically sorted) set of proof jobs.  Native views
    and typed cross-view links are retained without flattening.
    """

    bundle_id: str
    profile_id: str
    world_policy: WorldPolicyKind
    actions: tuple[ActionScope, ...]
    jobs: tuple[ProofJob, ...]
    invocation_digest: str = ""
    intent_cid: str = ""
    corpus_root: str = ""
    revocation_root: str = ""
    policy_root: str = ""
    legal_evidence_cids: tuple[str, ...] = ()
    security_evidence_cids: tuple[str, ...] = ()
    native_views: tuple[NativeViewBinding, ...] = ()
    cross_view_links: tuple[CrossViewLink, ...] = ()
    assumptions: tuple[str, ...] = ()
    config_digest: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = AUTHORIZATION_QUERY_BUNDLE_SCHEMA_VERSION
    interface: str = AUTHORIZATION_QUERY_COMPOSER_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "bundle_id", _text(self.bundle_id, "bundle_id")
        )
        object.__setattr__(
            self, "profile_id", _text(self.profile_id, "profile_id")
        )
        object.__setattr__(
            self,
            "world_policy",
            _enum(self.world_policy, WorldPolicyKind, "world_policy"),
        )
        if not self.actions:
            raise ComposeError("bundle requires at least one action scope")
        if len(self.actions) > MAX_ACTIONS:
            raise ComposeError(f"bundle exceeds MAX_ACTIONS ({MAX_ACTIONS})")
        actions = tuple(
            item
            if isinstance(item, ActionScope)
            else ActionScope.from_dict(_mapping(item, "action"))
            for item in self.actions
        )
        action_ids = [item.scope_key for item in actions]
        if len(action_ids) != len(set(action_ids)):
            raise ComposeError("action scopes must be unique by scope_key")
        object.__setattr__(
            self,
            "actions",
            tuple(sorted(actions, key=lambda item: item.scope_key)),
        )
        if not self.jobs:
            raise ComposeError("bundle requires at least one proof job")
        jobs = tuple(
            item
            if isinstance(item, ProofJob)
            else ProofJob.from_dict(_mapping(item, "job"))
            for item in self.jobs
        )
        job_ids = [item.job_id for item in jobs]
        if len(job_ids) != len(set(job_ids)):
            raise ComposeError("proof job IDs must be unique")
        # Deterministic job order: kind rank then job_id.
        kind_rank = {kind: index for index, kind in enumerate(ProofJobKind)}
        object.__setattr__(
            self,
            "jobs",
            tuple(
                sorted(
                    jobs,
                    key=lambda item: (
                        kind_rank.get(item.kind, 99),
                        item.action_id,
                        item.effect_id,
                        item.job_id,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "invocation_digest",
            _optional_digest(self.invocation_digest, "invocation_digest"),
        )
        object.__setattr__(
            self, "intent_cid", _optional_text(self.intent_cid, "intent_cid")
        )
        object.__setattr__(
            self, "corpus_root", _optional_text(self.corpus_root, "corpus_root")
        )
        object.__setattr__(
            self,
            "revocation_root",
            _optional_text(self.revocation_root, "revocation_root"),
        )
        object.__setattr__(
            self, "policy_root", _optional_text(self.policy_root, "policy_root")
        )
        object.__setattr__(
            self,
            "legal_evidence_cids",
            _unique_sorted_ids(
                self.legal_evidence_cids, "legal_evidence_cids"
            ),
        )
        object.__setattr__(
            self,
            "security_evidence_cids",
            _unique_sorted_ids(
                self.security_evidence_cids, "security_evidence_cids"
            ),
        )
        views = tuple(
            item
            if isinstance(item, NativeViewBinding)
            else NativeViewBinding.from_dict(_mapping(item, "native view"))
            for item in (self.native_views or ())
        )
        object.__setattr__(
            self,
            "native_views",
            tuple(sorted(views, key=lambda item: item.view_id)),
        )
        links = tuple(
            item
            if isinstance(item, CrossViewLink)
            else CrossViewLink.from_dict(_mapping(item, "cross-view link"))
            for item in (self.cross_view_links or ())
        )
        # Multiple native views may coexist; silent concatenation is rejected
        # per job (single logic_family) rather than across the whole bundle.
        object.__setattr__(
            self,
            "cross_view_links",
            tuple(sorted(links, key=lambda item: item.link_id)),
        )
        object.__setattr__(
            self,
            "assumptions",
            _unique_sorted_ids(self.assumptions, "assumptions"),
        )
        object.__setattr__(
            self,
            "config_digest",
            _optional_digest(self.config_digest, "config_digest"),
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != AUTHORIZATION_QUERY_BUNDLE_SCHEMA_VERSION:
            raise ComposeError(
                f"unsupported query bundle schema: {self.schema_version!r}"
            )
        if self.interface != AUTHORIZATION_QUERY_COMPOSER_INTERFACE:
            raise ComposeError(
                f"unsupported query bundle interface: {self.interface!r}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def jobs_for_action(self, action_id: str) -> tuple[ProofJob, ...]:
        return tuple(
            job for job in self.jobs if job.action_id == action_id
        )

    def jobs_of_kind(self, kind: ProofJobKind) -> tuple[ProofJob, ...]:
        kind = _enum(kind, ProofJobKind, "kind")
        return tuple(job for job in self.jobs if job.kind is kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [item.to_dict() for item in self.actions],
            "assumptions": list(self.assumptions),
            "bundle_id": self.bundle_id,
            "config_digest": self.config_digest,
            "corpus_root": self.corpus_root,
            "cross_view_links": [
                item.to_dict() for item in self.cross_view_links
            ],
            "intent_cid": self.intent_cid,
            "interface": self.interface,
            "invocation_digest": self.invocation_digest,
            "jobs": [item.to_dict() for item in self.jobs],
            "legal_evidence_cids": list(self.legal_evidence_cids),
            "metadata": self.metadata.to_dict(),
            "native_views": [item.to_dict() for item in self.native_views],
            "policy_root": self.policy_root,
            "profile_id": self.profile_id,
            "revocation_root": self.revocation_root,
            "schema_version": self.schema_version,
            "security_evidence_cids": list(self.security_evidence_cids),
            "world_policy": self.world_policy.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorizationQueryBundle":
        value = _mapping(value, "authorization query bundle")
        _reject_unknown(
            value,
            frozenset(
                {
                    "actions",
                    "assumptions",
                    "bundle_id",
                    "config_digest",
                    "corpus_root",
                    "cross_view_links",
                    "intent_cid",
                    "interface",
                    "invocation_digest",
                    "jobs",
                    "legal_evidence_cids",
                    "metadata",
                    "native_views",
                    "policy_root",
                    "profile_id",
                    "revocation_root",
                    "schema_version",
                    "security_evidence_cids",
                    "world_policy",
                }
            ),
            "authorization query bundle",
        )
        return cls(
            bundle_id=value.get("bundle_id", ""),
            profile_id=value.get("profile_id", ""),
            world_policy=value.get("world_policy", WorldPolicyKind.CLOSED),
            actions=tuple(value.get("actions", ())),
            jobs=tuple(value.get("jobs", ())),
            invocation_digest=value.get("invocation_digest", ""),
            intent_cid=value.get("intent_cid", ""),
            corpus_root=value.get("corpus_root", ""),
            revocation_root=value.get("revocation_root", ""),
            policy_root=value.get("policy_root", ""),
            legal_evidence_cids=tuple(value.get("legal_evidence_cids", ())),
            security_evidence_cids=tuple(
                value.get("security_evidence_cids", ())
            ),
            native_views=tuple(value.get("native_views", ())),
            cross_view_links=tuple(value.get("cross_view_links", ())),
            assumptions=tuple(value.get("assumptions", ())),
            config_digest=value.get("config_digest", ""),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get(
                "schema_version", AUTHORIZATION_QUERY_BUNDLE_SCHEMA_VERSION
            ),
            interface=value.get(
                "interface", AUTHORIZATION_QUERY_COMPOSER_INTERFACE
            ),
        )


# ---------------------------------------------------------------------------
# Job results and decision policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofJobResult:
    """Outcome of one proof job after portfolio selection (or direct inject)."""

    job_id: str
    kind: ProofJobKind
    verdict: JobVerdict
    authority_path: str = "theorem_proof"
    backend_id: str = ""
    attempt_ids: tuple[str, ...] = ()
    evidence_cids: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    reason: str = ""
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = JOB_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _text(self.job_id, "job_id"))
        object.__setattr__(self, "kind", _enum(self.kind, ProofJobKind, "kind"))
        object.__setattr__(
            self, "verdict", _enum(self.verdict, JobVerdict, "verdict")
        )
        object.__setattr__(
            self,
            "authority_path",
            _text(self.authority_path, "authority_path"),
        )
        object.__setattr__(
            self, "backend_id", _optional_text(self.backend_id, "backend_id")
        )
        object.__setattr__(
            self,
            "attempt_ids",
            _unique_sorted_ids(self.attempt_ids, "attempt_ids"),
        )
        object.__setattr__(
            self,
            "evidence_cids",
            _unique_sorted_ids(self.evidence_cids, "evidence_cids"),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _unique_sorted_ids(self.diagnostics, "diagnostics"),
        )
        if not isinstance(self.reason, str):
            raise ComposeError("reason must be a string")
        if len(self.reason) > MAX_REASON_CHARS:
            raise ComposeError("reason exceeds maximum length")
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != JOB_RESULT_SCHEMA_VERSION:
            raise ComposeError(
                f"unsupported job result schema: {self.schema_version!r}"
            )

    @property
    def is_proved(self) -> bool:
        return self.verdict is JobVerdict.PROVED

    @property
    def is_deny(self) -> bool:
        return self.verdict in {JobVerdict.DENIED, JobVerdict.DISPROVED}

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_ids": list(self.attempt_ids),
            "authority_path": self.authority_path,
            "backend_id": self.backend_id,
            "diagnostics": list(self.diagnostics),
            "evidence_cids": list(self.evidence_cids),
            "job_id": self.job_id,
            "kind": self.kind.value,
            "metadata": self.metadata.to_dict(),
            "reason": self.reason,
            "schema_version": self.schema_version,
            "verdict": self.verdict.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofJobResult":
        value = _mapping(value, "proof job result")
        _reject_unknown(
            value,
            frozenset(
                {
                    "attempt_ids",
                    "authority_path",
                    "backend_id",
                    "diagnostics",
                    "evidence_cids",
                    "job_id",
                    "kind",
                    "metadata",
                    "reason",
                    "schema_version",
                    "verdict",
                }
            ),
            "proof job result",
        )
        return cls(
            job_id=value.get("job_id", ""),
            kind=value.get("kind", ""),
            verdict=value.get("verdict", ""),
            authority_path=value.get("authority_path", "theorem_proof"),
            backend_id=value.get("backend_id", ""),
            attempt_ids=tuple(value.get("attempt_ids", ())),
            evidence_cids=tuple(value.get("evidence_cids", ())),
            diagnostics=tuple(value.get("diagnostics", ())),
            reason=value.get("reason", ""),
            metadata=FrozenMap(value.get("metadata", {})),
            schema_version=value.get(
                "schema_version", JOB_RESULT_SCHEMA_VERSION
            ),
        )


def map_internal_to_wire(
    status: InternalDecisionStatus,
) -> AdmissibilityStatus:
    """Map internal multi-status to the legacy allow/reject/abstain wire.

    * ``ALLOW`` → ``allow``
    * ``DENY`` → ``reject``
    * ``REVIEW`` / ``INDETERMINATE`` / ``ERROR`` → ``abstain``

    The richer internal status must not be reverse-inferred from a bare
    wire ``abstain`` without its bound receipt.
    """

    status = _enum(status, InternalDecisionStatus, "status")
    if status is InternalDecisionStatus.ALLOW:
        return AdmissibilityStatus.ALLOW
    if status is InternalDecisionStatus.DENY:
        return AdmissibilityStatus.REJECT
    return AdmissibilityStatus.ABSTAIN


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Internal authorization decision (AuthorizationDecision@1).

    Holds the multi-status outcome, job results, and the mapped wire status.
    Decisions never adopt proof authority: they only combine typed results.
    """

    status: InternalDecisionStatus
    wire_status: AdmissibilityStatus
    reasons: tuple[str, ...]
    job_results: tuple[ProofJobResult, ...]
    bundle_digest: str
    policy_digest: str
    profile_id: str
    reason_codes: tuple[str, ...] = ()
    selected_evidence_cids: tuple[str, ...] = ()
    residual_obligations: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    interface: str = AUTHORIZATION_DECISION_INTERFACE
    schema_version: str = AUTHORIZATION_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, InternalDecisionStatus, "status")
        )
        object.__setattr__(
            self,
            "wire_status",
            _enum(self.wire_status, AdmissibilityStatus, "wire_status"),
        )
        expected_wire = map_internal_to_wire(self.status)
        if self.wire_status is not expected_wire:
            raise ComposeError(
                f"wire_status {self.wire_status.value!r} inconsistent with "
                f"internal status {self.status.value!r} "
                f"(expected {expected_wire.value!r})"
            )
        object.__setattr__(
            self, "reasons", _unique_sorted_ids(self.reasons, "reasons")
        )
        results = tuple(
            item
            if isinstance(item, ProofJobResult)
            else ProofJobResult.from_dict(_mapping(item, "job result"))
            for item in self.job_results
        )
        object.__setattr__(
            self,
            "job_results",
            tuple(sorted(results, key=lambda item: item.job_id)),
        )
        object.__setattr__(
            self, "bundle_digest", _digest(self.bundle_digest, "bundle_digest")
        )
        object.__setattr__(
            self, "policy_digest", _digest(self.policy_digest, "policy_digest")
        )
        object.__setattr__(
            self, "profile_id", _text(self.profile_id, "profile_id")
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_sorted_ids(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self,
            "selected_evidence_cids",
            _unique_sorted_ids(
                self.selected_evidence_cids, "selected_evidence_cids"
            ),
        )
        object.__setattr__(
            self,
            "residual_obligations",
            _unique_sorted_ids(
                self.residual_obligations, "residual_obligations"
            ),
        )
        object.__setattr__(
            self,
            "diagnostics",
            _unique_sorted_ids(self.diagnostics, "diagnostics"),
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(self.metadata),
        )
        if self.interface != AUTHORIZATION_DECISION_INTERFACE:
            raise ComposeError(
                f"unsupported decision interface: {self.interface!r}"
            )
        if self.schema_version != AUTHORIZATION_DECISION_SCHEMA_VERSION:
            raise ComposeError(
                f"unsupported decision schema: {self.schema_version!r}"
            )

    @property
    def is_allow(self) -> bool:
        return self.status is InternalDecisionStatus.ALLOW

    @property
    def is_deny(self) -> bool:
        return self.status is InternalDecisionStatus.DENY

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_admissibility_reasons(self) -> tuple[AdmissibilityReason, ...]:
        """Project closed wire reasons from the decision (best-effort)."""

        projected: list[AdmissibilityReason] = []
        message = self.reasons[0] if self.reasons else ""
        for code in self.reason_codes:
            try:
                reason_code = AdmissibilityReasonCode(code)
            except ValueError:
                continue
            projected.append(
                AdmissibilityReason(
                    code=reason_code,
                    message=message or code,
                )
            )
        return tuple(projected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_digest": self.bundle_digest,
            "diagnostics": list(self.diagnostics),
            "interface": self.interface,
            "job_results": [item.to_dict() for item in self.job_results],
            "metadata": self.metadata.to_dict(),
            "policy_digest": self.policy_digest,
            "profile_id": self.profile_id,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "residual_obligations": list(self.residual_obligations),
            "schema_version": self.schema_version,
            "selected_evidence_cids": list(self.selected_evidence_cids),
            "status": self.status.value,
            "wire_status": self.wire_status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthorizationDecision":
        value = _mapping(value, "authorization decision")
        _reject_unknown(
            value,
            frozenset(
                {
                    "bundle_digest",
                    "diagnostics",
                    "interface",
                    "job_results",
                    "metadata",
                    "policy_digest",
                    "profile_id",
                    "reason_codes",
                    "reasons",
                    "residual_obligations",
                    "schema_version",
                    "selected_evidence_cids",
                    "status",
                    "wire_status",
                }
            ),
            "authorization decision",
        )
        return cls(
            status=value.get("status", ""),
            wire_status=value.get("wire_status", ""),
            reasons=tuple(value.get("reasons", ())),
            job_results=tuple(value.get("job_results", ())),
            bundle_digest=value.get("bundle_digest", ""),
            policy_digest=value.get("policy_digest", ""),
            profile_id=value.get("profile_id", ""),
            reason_codes=tuple(value.get("reason_codes", ())),
            selected_evidence_cids=tuple(
                value.get("selected_evidence_cids", ())
            ),
            residual_obligations=tuple(value.get("residual_obligations", ())),
            diagnostics=tuple(value.get("diagnostics", ())),
            metadata=FrozenMap(value.get("metadata", {})),
            interface=value.get("interface", AUTHORIZATION_DECISION_INTERFACE),
            schema_version=value.get(
                "schema_version", AUTHORIZATION_DECISION_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class AuthorizationDecisionPolicy:
    """``AuthorizationDecisionPolicy@1`` — closed deny-overrides combiner.

    Closed profiles require:

    * an **applicable positive grant** proved under theorem authority; and
    * a **proved non-conflict** obligation (not "no retrieved deny");
    * hard Security invariants, pre-dispatch obligations, and coverage.

    Selection is order-independent: reordering input job results never changes
    the decision.  Deny always overrides grants.
    """

    policy_id: str
    combining_rule: CombiningRule = CombiningRule.DENY_OVERRIDES
    world_policy: WorldPolicyKind = WorldPolicyKind.CLOSED
    require_positive_grant: bool = True
    require_proved_non_conflict: bool = True
    require_security_invariants: bool = True
    require_pre_dispatch_obligations: bool = True
    require_coverage: bool = True
    require_context_binding: bool = True
    require_applicability: bool = True
    accept_no_retrieved_deny_as_non_conflict: bool = False
    allowed_authority_paths: tuple[str, ...] = ("theorem_proof",)
    profile_id: str = "legal-strict"
    schema_version: str = AUTHORIZATION_DECISION_POLICY_SCHEMA_VERSION
    interface: str = AUTHORIZATION_DECISION_POLICY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_id", _text(self.policy_id, "policy_id")
        )
        object.__setattr__(
            self,
            "combining_rule",
            _enum(self.combining_rule, CombiningRule, "combining_rule"),
        )
        object.__setattr__(
            self,
            "world_policy",
            _enum(self.world_policy, WorldPolicyKind, "world_policy"),
        )
        for flag_name in (
            "require_positive_grant",
            "require_proved_non_conflict",
            "require_security_invariants",
            "require_pre_dispatch_obligations",
            "require_coverage",
            "require_context_binding",
            "require_applicability",
            "accept_no_retrieved_deny_as_non_conflict",
        ):
            if not isinstance(getattr(self, flag_name), bool):
                raise ComposeError(f"{flag_name} must be a bool")
        # Closed world forbids the weak "no deny found" shortcut.
        if (
            self.world_policy is WorldPolicyKind.CLOSED
            and self.accept_no_retrieved_deny_as_non_conflict
        ):
            raise ComposeError(
                "closed-world decision policy cannot treat absence of a "
                "retrieved deny as proved non-conflict"
            )
        if self.world_policy is WorldPolicyKind.CLOSED:
            if not self.require_positive_grant:
                raise ComposeError(
                    "closed-world policy requires an applicable positive grant"
                )
            if not self.require_proved_non_conflict:
                raise ComposeError(
                    "closed-world policy requires proved non-conflict"
                )
        object.__setattr__(
            self,
            "allowed_authority_paths",
            _unique_sorted_ids(
                self.allowed_authority_paths, "allowed_authority_paths"
            ),
        )
        if not self.allowed_authority_paths:
            raise ComposeError("allowed_authority_paths must not be empty")
        forbidden = set(self.allowed_authority_paths) & NON_ALLOWING_AUTHORITY_PATHS
        if forbidden:
            raise ComposeError(
                "allowed_authority_paths cannot include non-allowing paths: "
                + ", ".join(sorted(forbidden))
            )
        object.__setattr__(
            self, "profile_id", _text(self.profile_id, "profile_id")
        )
        if self.interface != AUTHORIZATION_DECISION_POLICY_INTERFACE:
            raise ComposeError(
                f"unsupported decision policy interface: {self.interface!r}"
            )
        if self.schema_version != AUTHORIZATION_DECISION_POLICY_SCHEMA_VERSION:
            raise ComposeError(
                f"unsupported decision policy schema: {self.schema_version!r}"
            )

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "accept_no_retrieved_deny_as_non_conflict": (
                self.accept_no_retrieved_deny_as_non_conflict
            ),
            "allowed_authority_paths": list(self.allowed_authority_paths),
            "combining_rule": self.combining_rule.value,
            "interface": self.interface,
            "policy_id": self.policy_id,
            "profile_id": self.profile_id,
            "require_applicability": self.require_applicability,
            "require_context_binding": self.require_context_binding,
            "require_coverage": self.require_coverage,
            "require_positive_grant": self.require_positive_grant,
            "require_pre_dispatch_obligations": (
                self.require_pre_dispatch_obligations
            ),
            "require_proved_non_conflict": self.require_proved_non_conflict,
            "require_security_invariants": self.require_security_invariants,
            "schema_version": self.schema_version,
            "world_policy": self.world_policy.value,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "AuthorizationDecisionPolicy":
        value = _mapping(value, "authorization decision policy")
        _reject_unknown(
            value,
            frozenset(
                {
                    "accept_no_retrieved_deny_as_non_conflict",
                    "allowed_authority_paths",
                    "combining_rule",
                    "interface",
                    "policy_id",
                    "profile_id",
                    "require_applicability",
                    "require_context_binding",
                    "require_coverage",
                    "require_positive_grant",
                    "require_pre_dispatch_obligations",
                    "require_proved_non_conflict",
                    "require_security_invariants",
                    "schema_version",
                    "world_policy",
                }
            ),
            "authorization decision policy",
        )
        return cls(
            policy_id=value.get("policy_id", ""),
            combining_rule=value.get(
                "combining_rule", CombiningRule.DENY_OVERRIDES
            ),
            world_policy=value.get("world_policy", WorldPolicyKind.CLOSED),
            require_positive_grant=bool(
                value.get("require_positive_grant", True)
            ),
            require_proved_non_conflict=bool(
                value.get("require_proved_non_conflict", True)
            ),
            require_security_invariants=bool(
                value.get("require_security_invariants", True)
            ),
            require_pre_dispatch_obligations=bool(
                value.get("require_pre_dispatch_obligations", True)
            ),
            require_coverage=bool(value.get("require_coverage", True)),
            require_context_binding=bool(
                value.get("require_context_binding", True)
            ),
            require_applicability=bool(
                value.get("require_applicability", True)
            ),
            accept_no_retrieved_deny_as_non_conflict=bool(
                value.get("accept_no_retrieved_deny_as_non_conflict", False)
            ),
            allowed_authority_paths=tuple(
                value.get("allowed_authority_paths", ("theorem_proof",))
            ),
            profile_id=value.get("profile_id", "legal-strict"),
            schema_version=value.get(
                "schema_version", AUTHORIZATION_DECISION_POLICY_SCHEMA_VERSION
            ),
            interface=value.get(
                "interface", AUTHORIZATION_DECISION_POLICY_INTERFACE
            ),
        )

    @classmethod
    def for_profile(
        cls,
        profile: AdmissibilityProfile
        | AdmissibilityProfileId
        | str
        | None = None,
        *,
        policy_id: str = "policy:deny-overrides-closed",
    ) -> "AuthorizationDecisionPolicy":
        """Build a closed deny-overrides policy for an admissibility profile."""

        resolution = resolve_profile_fail_closed(profile)
        if not resolution.ok or resolution.profile is None:
            requested = resolution.requested or profile
            raise ComposeError(
                f"cannot build decision policy for unresolved profile: "
                f"{requested!r}"
            )
        resolved = resolution.profile
        return cls(
            policy_id=policy_id,
            combining_rule=CombiningRule.DENY_OVERRIDES,
            world_policy=WorldPolicyKind.CLOSED,
            require_positive_grant=True,
            require_proved_non_conflict=True,
            require_security_invariants=resolved.require_security_constraints,
            require_pre_dispatch_obligations=True,
            require_coverage=True,
            require_context_binding=True,
            require_applicability=True,
            accept_no_retrieved_deny_as_non_conflict=False,
            allowed_authority_paths=("theorem_proof",),
            profile_id=resolved.profile_id.value,
        )

    def evaluate(
        self,
        bundle: AuthorizationQueryBundle,
        results: Sequence[ProofJobResult] | Iterable[ProofJobResult],
    ) -> AuthorizationDecision:
        """Combine job results under deny-overrides (order independent)."""

        if not isinstance(bundle, AuthorizationQueryBundle):
            raise TypeError("bundle must be an AuthorizationQueryBundle")
        # Canonical sort — order of *results* must never affect outcome.
        ordered = tuple(
            sorted(
                (
                    item
                    if isinstance(item, ProofJobResult)
                    else ProofJobResult.from_dict(_mapping(item, "job result"))
                    for item in results
                ),
                key=lambda item: (item.kind.value, item.job_id, item.digest),
            )
        )
        by_job: dict[str, ProofJobResult] = {}
        diagnostics: list[str] = []
        reasons: list[str] = []
        reason_codes: list[str] = []
        residual: list[str] = []
        evidence: list[str] = []

        for result in ordered:
            previous = by_job.get(result.job_id)
            if previous is not None and previous.digest != result.digest:
                diagnostics.append(
                    f"auth.decision.duplicate_job_conflict:{result.job_id}"
                )
            by_job[result.job_id] = result
            evidence.extend(result.evidence_cids)

        # Missing required jobs → indeterminate (fail closed).
        missing_jobs = [
            job.job_id for job in bundle.jobs if job.job_id not in by_job
        ]
        if missing_jobs:
            diagnostics.extend(
                f"auth.decision.missing_job_result:{job_id}"
                for job_id in sorted(missing_jobs)
            )

        def _results_of(kind: ProofJobKind) -> list[ProofJobResult]:
            return [
                by_job[job.job_id]
                for job in bundle.jobs
                if job.kind is kind and job.job_id in by_job
            ]

        # --- Deny overrides: any hard deny / disproof wins immediately. ---
        deny_results = [
            result
            for result in by_job.values()
            if result.is_deny
            or result.verdict is JobVerdict.DISPROVED
        ]
        if deny_results:
            for result in sorted(deny_results, key=lambda item: item.job_id):
                reasons.append(
                    result.reason
                    or f"deny from {result.kind.value}:{result.job_id}"
                )
                if result.kind is ProofJobKind.SECURITY_INVARIANT:
                    reason_codes.append(
                        AdmissibilityReasonCode.SECURITY_HARD_CONSTRAINT.value
                    )
                elif result.kind is ProofJobKind.POSITIVE_GRANT:
                    reason_codes.append(
                        AdmissibilityReasonCode.LEGAL_HARD_CONSTRAINT.value
                    )
                else:
                    reason_codes.append(
                        AdmissibilityReasonCode.CONSTRAINT_CONTRADICTION.value
                    )
            diagnostics.append("auth.decision.deny_overrides")
            return AuthorizationDecision(
                status=InternalDecisionStatus.DENY,
                wire_status=AdmissibilityStatus.REJECT,
                reasons=tuple(reasons),
                job_results=ordered,
                bundle_digest=bundle.digest,
                policy_digest=self.digest,
                profile_id=self.profile_id,
                reason_codes=tuple(sorted(set(reason_codes))),
                selected_evidence_cids=tuple(sorted(set(evidence))),
                residual_obligations=(),
                diagnostics=tuple(sorted(set(diagnostics))),
            )

        # --- Non-allowing authority paths cannot allow. ---
        non_allowing = [
            result
            for result in by_job.values()
            if (
                result.authority_path in NON_ALLOWING_AUTHORITY_PATHS
                or result.verdict
                in {
                    JobVerdict.SAT_ONLY,
                    JobVerdict.MODEL,
                    JobVerdict.MONITOR,
                    JobVerdict.EVIDENCE,
                    JobVerdict.POLICY,
                    JobVerdict.SIMULATION,
                    JobVerdict.UNSUPPORTED,
                    JobVerdict.UNKNOWN,
                    JobVerdict.UNAVAILABLE,
                    JobVerdict.CONTRADICTORY,
                    JobVerdict.TIMEOUT,
                    JobVerdict.ERROR,
                }
            )
            and result.kind
            in {
                ProofJobKind.POSITIVE_GRANT,
                ProofJobKind.NON_CONFLICT,
                ProofJobKind.SECURITY_INVARIANT,
                ProofJobKind.APPLICABILITY,
                ProofJobKind.COVERAGE,
                ProofJobKind.CONTEXT_BINDING,
                ProofJobKind.OBLIGATION_PRE,
            }
        ]
        # Also catch any result whose authority path is outside allowlist
        # when claiming proved.
        for result in by_job.values():
            if (
                result.is_proved
                and result.authority_path not in self.allowed_authority_paths
            ):
                non_allowing.append(result)
                diagnostics.append(
                    f"auth.decision.authority_not_allowlisted:"
                    f"{result.job_id}:{result.authority_path}"
                )

        # Contradictory / review / error paths.
        if any(r.verdict is JobVerdict.CONTRADICTORY for r in by_job.values()):
            diagnostics.append("auth.decision.contradictory_results")
            reasons.append("contradictory authoritative backend results")
            reason_codes.append(
                AdmissibilityReasonCode.CONSTRAINT_CONTRADICTION.value
            )
            return AuthorizationDecision(
                status=InternalDecisionStatus.REVIEW,
                wire_status=AdmissibilityStatus.ABSTAIN,
                reasons=tuple(reasons),
                job_results=ordered,
                bundle_digest=bundle.digest,
                policy_digest=self.digest,
                profile_id=self.profile_id,
                reason_codes=tuple(sorted(set(reason_codes))),
                selected_evidence_cids=tuple(sorted(set(evidence))),
                residual_obligations=tuple(
                    job.job_id
                    for job in bundle.jobs
                    if job.job_id not in by_job
                    or not by_job[job.job_id].is_proved
                ),
                diagnostics=tuple(sorted(set(diagnostics))),
            )

        if any(r.verdict is JobVerdict.ERROR for r in by_job.values()):
            diagnostics.append("auth.decision.error_path")
            reasons.append("backend or evaluation error; fail closed")
            reason_codes.append(
                AdmissibilityReasonCode.INTEGRITY_FAILURE.value
            )
            return AuthorizationDecision(
                status=InternalDecisionStatus.ERROR,
                wire_status=AdmissibilityStatus.ABSTAIN,
                reasons=tuple(reasons),
                job_results=ordered,
                bundle_digest=bundle.digest,
                policy_digest=self.digest,
                profile_id=self.profile_id,
                reason_codes=tuple(sorted(set(reason_codes))),
                selected_evidence_cids=tuple(sorted(set(evidence))),
                residual_obligations=tuple(
                    r.job_id for r in by_job.values() if not r.is_proved
                ),
                diagnostics=tuple(sorted(set(diagnostics))),
            )

        if any(r.verdict is JobVerdict.REVIEW for r in by_job.values()):
            diagnostics.append("auth.decision.review_required")
            reasons.append("policy-mandated review or resolvable ambiguity")
            reason_codes.append(
                AdmissibilityReasonCode.MISSING_EVIDENCE.value
            )
            return AuthorizationDecision(
                status=InternalDecisionStatus.REVIEW,
                wire_status=AdmissibilityStatus.ABSTAIN,
                reasons=tuple(reasons),
                job_results=ordered,
                bundle_digest=bundle.digest,
                policy_digest=self.digest,
                profile_id=self.profile_id,
                reason_codes=tuple(sorted(set(reason_codes))),
                selected_evidence_cids=tuple(sorted(set(evidence))),
                residual_obligations=tuple(
                    r.job_id for r in by_job.values() if not r.is_proved
                ),
                diagnostics=tuple(sorted(set(diagnostics))),
            )

        # Closed-profile positive gates.
        def _gate_proved(kind: ProofJobKind, required: bool) -> bool:
            if not required:
                return True
            kind_results = _results_of(kind)
            if not kind_results:
                residual.append(f"missing:{kind.value}")
                diagnostics.append(f"auth.decision.missing_required:{kind.value}")
                return False
            # All instances of this kind must be theorem-proved under allowlist.
            for result in kind_results:
                if not result.is_proved:
                    residual.append(result.job_id)
                    diagnostics.append(
                        f"auth.decision.unproved:{kind.value}:{result.verdict.value}"
                    )
                    return False
                if result.authority_path not in self.allowed_authority_paths:
                    residual.append(result.job_id)
                    diagnostics.append(
                        f"auth.decision.weak_authority:"
                        f"{kind.value}:{result.authority_path}"
                    )
                    return False
            return True

        gates = (
            (ProofJobKind.APPLICABILITY, self.require_applicability),
            (ProofJobKind.POSITIVE_GRANT, self.require_positive_grant),
            (ProofJobKind.NON_CONFLICT, self.require_proved_non_conflict),
            (
                ProofJobKind.SECURITY_INVARIANT,
                self.require_security_invariants,
            ),
            (
                ProofJobKind.OBLIGATION_PRE,
                self.require_pre_dispatch_obligations,
            ),
            (ProofJobKind.COVERAGE, self.require_coverage),
            (ProofJobKind.CONTEXT_BINDING, self.require_context_binding),
        )
        all_gates = all(_gate_proved(kind, required) for kind, required in gates)

        # Explicit rejection of the "no retrieved deny" shortcut:
        # non-conflict must be proved, not inferred from empty deny retrieval.
        non_conflict_results = _results_of(ProofJobKind.NON_CONFLICT)
        for result in non_conflict_results:
            if result.metadata.get("no_retrieved_deny") is True and result.is_proved:
                if not self.accept_no_retrieved_deny_as_non_conflict:
                    all_gates = False
                    residual.append(result.job_id)
                    diagnostics.append(
                        "auth.decision.no_retrieved_deny_is_not_non_conflict"
                    )
                    reasons.append(
                        "closed profile requires proved non-conflict; "
                        "absence of a retrieved deny is not sufficient"
                    )

        if non_allowing and not all_gates:
            # Already reflected in residual/diagnostics.
            pass
        elif non_allowing and all_gates:
            # A non-allowing path claimed proved — reject that claim.
            all_gates = False
            for result in non_allowing:
                residual.append(result.job_id)
                diagnostics.append(
                    f"auth.decision.non_allowing_path:"
                    f"{result.verdict.value}:{result.authority_path}"
                )

        if missing_jobs or not all_gates:
            diagnostics.append("auth.decision.indeterminate")
            if not reasons:
                reasons.append(
                    "incomplete evidence, unproved gates, or non-allowing path"
                )
            reason_codes.append(AdmissibilityReasonCode.MISSING_EVIDENCE.value)
            if any(
                r.verdict is JobVerdict.UNAVAILABLE for r in by_job.values()
            ):
                reason_codes.append(
                    AdmissibilityReasonCode.PROVER_UNAVAILABLE.value
                )
            if any(
                r.verdict is JobVerdict.UNSUPPORTED for r in by_job.values()
            ):
                reason_codes.append(
                    AdmissibilityReasonCode.SEMANTICS_UNSUPPORTED.value
                )
            return AuthorizationDecision(
                status=InternalDecisionStatus.INDETERMINATE,
                wire_status=AdmissibilityStatus.ABSTAIN,
                reasons=tuple(sorted(set(reasons))),
                job_results=ordered,
                bundle_digest=bundle.digest,
                policy_digest=self.digest,
                profile_id=self.profile_id,
                reason_codes=tuple(sorted(set(reason_codes))),
                selected_evidence_cids=tuple(sorted(set(evidence))),
                residual_obligations=tuple(sorted(set(residual))),
                diagnostics=tuple(sorted(set(diagnostics))),
            )

        # All closed gates theorem-proved under allowlisted authority.
        diagnostics.append("auth.decision.allow")
        reasons.append(
            "applicable positive grant and proved non-conflict under closed profile"
        )
        reason_codes.append(
            AdmissibilityReasonCode.OBLIGATIONS_SUPPORTED.value
        )
        residual_post = [
            job.job_id
            for job in bundle.jobs
            if job.kind
            in {ProofJobKind.OBLIGATION_DURING, ProofJobKind.OBLIGATION_POST}
            and (
                job.job_id not in by_job or not by_job[job.job_id].is_proved
            )
        ]
        return AuthorizationDecision(
            status=InternalDecisionStatus.ALLOW,
            wire_status=AdmissibilityStatus.ALLOW,
            reasons=tuple(reasons),
            job_results=ordered,
            bundle_digest=bundle.digest,
            policy_digest=self.digest,
            profile_id=self.profile_id,
            reason_codes=tuple(sorted(set(reason_codes))),
            selected_evidence_cids=tuple(sorted(set(evidence))),
            residual_obligations=tuple(sorted(set(residual_post))),
            diagnostics=tuple(sorted(set(diagnostics))),
        )


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


def _job_id(action: ActionScope, kind: ProofJobKind) -> str:
    effect = action.effect_id or action.action_id
    return f"job:{kind.value}:{action.action_id}:{effect}"


def _default_jobs_for_action(
    action: ActionScope,
    *,
    world_policy: WorldPolicyKind,
    view_ids: Sequence[str] = (),
    cross_view_link_ids: Sequence[str] = (),
    legal_evidence: Sequence[str] = (),
    security_evidence: Sequence[str] = (),
    include_during_post: bool = True,
    include_translation_reconstruction: bool = True,
) -> list[ProofJob]:
    """Emit the closed set of proof jobs for one action/effect."""

    shared_kwargs = {
        "action_id": action.action_id,
        "effect_id": action.effect_id,
        "logic_family": action.logic_family,
        "domain": action.domain,
        "view_ids": tuple(view_ids),
        "cross_view_link_ids": tuple(cross_view_link_ids),
        "world_policy": world_policy,
    }
    jobs: list[ProofJob] = [
        ProofJob(
            job_id=_job_id(action, ProofJobKind.APPLICABILITY),
            kind=ProofJobKind.APPLICABILITY,
            query_kind=QueryKind.THEOREM_PROOF,
            required_authority=AuthorityKind.THEOREM_PROOF,
            statement=(
                f"Applicability of authorities for action {action.action_id}"
            ),
            constraint_roles=(
                ConstraintRole.PREMISE.value,
                ConstraintRole.CLAIM.value,
            ),
            evidence_cids=tuple(
                sorted(set(legal_evidence) | set(security_evidence))
            ),
            **shared_kwargs,
        ),
        ProofJob(
            job_id=_job_id(action, ProofJobKind.POSITIVE_GRANT),
            kind=ProofJobKind.POSITIVE_GRANT,
            query_kind=QueryKind.THEOREM_PROOF,
            required_authority=AuthorityKind.THEOREM_PROOF,
            statement=(
                f"Explicit applicable positive grant for {action.action_id}"
            ),
            constraint_roles=(ConstraintRole.GRANT.value,),
            evidence_cids=tuple(sorted(set(legal_evidence))),
            **shared_kwargs,
        ),
        ProofJob(
            job_id=_job_id(action, ProofJobKind.NON_CONFLICT),
            kind=ProofJobKind.NON_CONFLICT,
            query_kind=QueryKind.THEOREM_PROOF,
            required_authority=AuthorityKind.THEOREM_PROOF,
            statement=(
                f"Proved non-conflict (applicable prohibition check) for "
                f"{action.action_id}"
            ),
            constraint_roles=(
                ConstraintRole.PROHIBITION.value,
                ConstraintRole.EXCEPTION.value,
            ),
            evidence_cids=tuple(
                sorted(set(legal_evidence) | set(security_evidence))
            ),
            **shared_kwargs,
        ),
        ProofJob(
            job_id=_job_id(action, ProofJobKind.SECURITY_INVARIANT),
            kind=ProofJobKind.SECURITY_INVARIANT,
            query_kind=QueryKind.THEOREM_PROOF,
            required_authority=AuthorityKind.THEOREM_PROOF,
            statement=f"Hard Security invariants for {action.action_id}",
            constraint_roles=(ConstraintRole.INVARIANT.value,),
            evidence_cids=tuple(sorted(set(security_evidence))),
            domain="security",
            logic_family=action.logic_family,
            action_id=action.action_id,
            effect_id=action.effect_id,
            view_ids=tuple(view_ids),
            cross_view_link_ids=tuple(cross_view_link_ids),
            world_policy=world_policy,
        ),
        ProofJob(
            job_id=_job_id(action, ProofJobKind.OBLIGATION_PRE),
            kind=ProofJobKind.OBLIGATION_PRE,
            query_kind=QueryKind.THEOREM_PROOF,
            required_authority=AuthorityKind.THEOREM_PROOF,
            statement=f"Pre-dispatch obligations for {action.action_id}",
            constraint_roles=(ConstraintRole.OBLIGATION.value,),
            evidence_cids=tuple(
                sorted(set(legal_evidence) | set(security_evidence))
            ),
            **shared_kwargs,
        ),
        ProofJob(
            job_id=_job_id(action, ProofJobKind.COVERAGE),
            kind=ProofJobKind.COVERAGE,
            query_kind=QueryKind.THEOREM_PROOF,
            required_authority=AuthorityKind.THEOREM_PROOF,
            statement=f"Corpus/evidence coverage for {action.action_id}",
            constraint_roles=(ConstraintRole.PREMISE.value,),
            evidence_cids=tuple(
                sorted(set(legal_evidence) | set(security_evidence))
            ),
            **shared_kwargs,
        ),
        ProofJob(
            job_id=_job_id(action, ProofJobKind.CONTEXT_BINDING),
            kind=ProofJobKind.CONTEXT_BINDING,
            query_kind=QueryKind.THEOREM_PROOF,
            required_authority=AuthorityKind.THEOREM_PROOF,
            statement=(
                f"Exact decision-context binding for {action.action_id}"
            ),
            constraint_roles=(ConstraintRole.CLAIM.value,),
            evidence_cids=(),
            **shared_kwargs,
        ),
        ProofJob(
            job_id=_job_id(action, ProofJobKind.CONSISTENCY),
            kind=ProofJobKind.CONSISTENCY,
            query_kind=QueryKind.THEOREM_PROOF,
            required_authority=AuthorityKind.THEOREM_PROOF,
            statement=f"Cross-view consistency for {action.action_id}",
            constraint_roles=(ConstraintRole.CLAIM.value,),
            evidence_cids=tuple(
                sorted(set(legal_evidence) | set(security_evidence))
            ),
            **shared_kwargs,
        ),
    ]
    if include_during_post:
        jobs.extend(
            [
                ProofJob(
                    job_id=_job_id(action, ProofJobKind.OBLIGATION_DURING),
                    kind=ProofJobKind.OBLIGATION_DURING,
                    query_kind=QueryKind.THEOREM_PROOF,
                    required_authority=AuthorityKind.THEOREM_PROOF,
                    statement=(
                        f"During-use residual obligations for {action.action_id}"
                    ),
                    constraint_roles=(ConstraintRole.OBLIGATION.value,),
                    evidence_cids=tuple(sorted(set(legal_evidence))),
                    **shared_kwargs,
                ),
                ProofJob(
                    job_id=_job_id(action, ProofJobKind.OBLIGATION_POST),
                    kind=ProofJobKind.OBLIGATION_POST,
                    query_kind=QueryKind.THEOREM_PROOF,
                    required_authority=AuthorityKind.THEOREM_PROOF,
                    statement=(
                        f"Post-use residual obligations for {action.action_id}"
                    ),
                    constraint_roles=(ConstraintRole.OBLIGATION.value,),
                    evidence_cids=tuple(sorted(set(legal_evidence))),
                    **shared_kwargs,
                ),
            ]
        )
    if include_translation_reconstruction:
        jobs.extend(
            [
                ProofJob(
                    job_id=_job_id(action, ProofJobKind.TRANSLATION),
                    kind=ProofJobKind.TRANSLATION,
                    query_kind=QueryKind.THEOREM_PROOF,
                    required_authority=AuthorityKind.THEOREM_PROOF,
                    statement=(
                        f"Translation fidelity obligations for {action.action_id}"
                    ),
                    constraint_roles=(ConstraintRole.ASSUMPTION.value,),
                    **shared_kwargs,
                ),
                ProofJob(
                    job_id=_job_id(action, ProofJobKind.RECONSTRUCTION),
                    kind=ProofJobKind.RECONSTRUCTION,
                    query_kind=QueryKind.THEOREM_PROOF,
                    required_authority=AuthorityKind.THEOREM_PROOF,
                    statement=(
                        f"Reconstruction obligations for {action.action_id}"
                    ),
                    constraint_roles=(ConstraintRole.ASSUMPTION.value,),
                    **shared_kwargs,
                ),
            ]
        )
    if len(jobs) > MAX_JOBS_PER_ACTION:
        raise ComposeError(
            f"jobs per action exceed MAX_JOBS_PER_ACTION ({MAX_JOBS_PER_ACTION})"
        )
    return jobs


@dataclass(frozen=True, slots=True)
class AuthorizationQueryComposer:
    """``AuthorizationQueryComposer@1`` — compose authorization proof jobs.

    Produces an :class:`AuthorizationQueryBundle` from action scopes, selected
    Legal/Security evidence, native views, and typed cross-view links.  Does
    not execute backends or install solvers.
    """

    interface: str = AUTHORIZATION_QUERY_COMPOSER_INTERFACE
    schema_version: str = AUTHORIZATION_QUERY_COMPOSER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.interface != AUTHORIZATION_QUERY_COMPOSER_INTERFACE:
            raise ComposeError(
                f"unsupported composer interface: {self.interface!r}"
            )
        if self.schema_version != AUTHORIZATION_QUERY_COMPOSER_SCHEMA_VERSION:
            raise ComposeError(
                f"unsupported composer schema: {self.schema_version!r}"
            )

    def compose(
        self,
        actions: Sequence[ActionScope | Mapping[str, Any]],
        *,
        profile: AdmissibilityProfile
        | AdmissibilityProfileId
        | str
        | None = None,
        world_policy: WorldPolicyKind | str = WorldPolicyKind.CLOSED,
        invocation_digest: str = "",
        intent_cid: str = "",
        corpus_root: str = "",
        revocation_root: str = "",
        policy_root: str = "",
        legal_evidence_cids: Sequence[str] = (),
        security_evidence_cids: Sequence[str] = (),
        native_views: Sequence[NativeViewBinding | Mapping[str, Any]] = (),
        cross_view_links: Sequence[CrossViewLink | Mapping[str, Any]] = (),
        constraint_artifacts: Sequence[
            ConstraintArtifact | Mapping[str, Any]
        ] = (),
        assumptions: Sequence[str] = (),
        include_during_post: bool = True,
        include_translation_reconstruction: bool = True,
        metadata: Mapping[str, Any] | None = None,
        bundle_id: str = "",
    ) -> AuthorizationQueryBundle:
        """Compose a deterministic authorization query bundle.

        Closed profiles emit positive-grant and non-conflict as **distinct**
        jobs.  Absence of a retrieved deny is never used as non-conflict.
        """

        resolution = resolve_profile_fail_closed(profile)
        if not resolution.ok or resolution.profile is None:
            requested = resolution.requested or profile
            raise ComposeError(
                f"profile resolution failed closed: {requested!r}"
            )
        profile_obj = resolution.profile
        world = _enum(world_policy, WorldPolicyKind, "world_policy")
        if not actions:
            raise ComposeError("compose requires at least one action scope")

        scopes = tuple(
            item
            if isinstance(item, ActionScope)
            else ActionScope.from_dict(_mapping(item, "action"))
            for item in actions
        )

        views: list[NativeViewBinding] = []
        for item in native_views:
            views.append(
                item
                if isinstance(item, NativeViewBinding)
                else NativeViewBinding.from_dict(_mapping(item, "native view"))
            )
        # Pull native views from constraint artifacts without flattening.
        for artifact in constraint_artifacts:
            if not isinstance(artifact, ConstraintArtifact):
                if isinstance(artifact, Mapping):
                    artifact = ConstraintArtifact.from_dict(artifact)
                else:
                    raise ComposeError(
                        "constraint_artifacts must be ConstraintArtifact instances"
                    )
            views.extend(artifact.native_views)

        links: list[CrossViewLink] = []
        for item in cross_view_links:
            links.append(
                item
                if isinstance(item, CrossViewLink)
                else CrossViewLink.from_dict(
                    _mapping(item, "cross-view link")
                )
            )

        view_ids = tuple(sorted({view.view_id for view in views}))
        link_ids = tuple(sorted({link.link_id for link in links}))
        legal = tuple(sorted(set(legal_evidence_cids)))
        security = tuple(sorted(set(security_evidence_cids)))

        jobs: list[ProofJob] = []
        for scope in scopes:
            jobs.extend(
                _default_jobs_for_action(
                    scope,
                    world_policy=world,
                    view_ids=view_ids,
                    cross_view_link_ids=link_ids,
                    legal_evidence=legal,
                    security_evidence=security,
                    include_during_post=include_during_post,
                    include_translation_reconstruction=(
                        include_translation_reconstruction
                    ),
                )
            )

        config_digest = stable_digest(
            {
                "interface": self.interface,
                "profile_id": profile_obj.profile_id.value,
                "schema_version": self.schema_version,
                "world_policy": world.value,
            }
        )
        # Bundle identity is order-independent over action scopes.
        resolved_bundle_id = bundle_id or (
            "bundle:"
            + _sha256_hex(
                {
                    "actions": sorted(s.scope_key for s in scopes),
                    "config": config_digest,
                    "invocation": invocation_digest,
                }
            )[:24]
        )
        return AuthorizationQueryBundle(
            bundle_id=resolved_bundle_id,
            profile_id=profile_obj.profile_id.value,
            world_policy=world,
            actions=scopes,
            jobs=tuple(jobs),
            invocation_digest=invocation_digest,
            intent_cid=intent_cid,
            corpus_root=corpus_root,
            revocation_root=revocation_root,
            policy_root=policy_root,
            legal_evidence_cids=legal,
            security_evidence_cids=security,
            native_views=tuple(views),
            cross_view_links=tuple(links),
            assumptions=tuple(assumptions),
            config_digest=config_digest,
            metadata=FrozenMap(metadata or {}),
        )


def compose_authorization_query(
    actions: Sequence[ActionScope | Mapping[str, Any]],
    **kwargs: Any,
) -> AuthorizationQueryBundle:
    """Module-level helper: compose an authorization query bundle."""

    return AuthorizationQueryComposer().compose(actions, **kwargs)


def evaluate_authorization_decision(
    bundle: AuthorizationQueryBundle,
    results: Sequence[ProofJobResult] | Iterable[ProofJobResult],
    policy: AuthorizationDecisionPolicy | None = None,
) -> AuthorizationDecision:
    """Module-level helper: evaluate job results under a decision policy."""

    if policy is None:
        policy = AuthorizationDecisionPolicy.for_profile(bundle.profile_id)
    return policy.evaluate(bundle, results)


__all__ = [
    "ACTION_SCOPE_SCHEMA_VERSION",
    "AUTHORIZATION_DECISION_INTERFACE",
    "AUTHORIZATION_DECISION_POLICY_INTERFACE",
    "AUTHORIZATION_DECISION_POLICY_SCHEMA_VERSION",
    "AUTHORIZATION_DECISION_SCHEMA_VERSION",
    "AUTHORIZATION_QUERY_BUNDLE_SCHEMA_VERSION",
    "AUTHORIZATION_QUERY_COMPOSER_INTERFACE",
    "AUTHORIZATION_QUERY_COMPOSER_SCHEMA_VERSION",
    "ActionScope",
    "AuthorizationDecision",
    "AuthorizationDecisionPolicy",
    "AuthorizationQueryBundle",
    "AuthorizationQueryComposer",
    "CLOSED_PROFILE_REQUIRED_JOBS",
    "CombiningRule",
    "ComposeError",
    "InternalDecisionStatus",
    "JOB_RESULT_SCHEMA_VERSION",
    "JobVerdict",
    "NON_ALLOWING_AUTHORITY_PATHS",
    "PROOF_JOB_SCHEMA_VERSION",
    "ProofJob",
    "ProofJobKind",
    "ProofJobResult",
    "compose_authorization_query",
    "evaluate_authorization_decision",
    "map_internal_to_wire",
]
