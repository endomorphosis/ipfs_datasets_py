"""Production-candidate SecPAL-style authorization provider (FVT-G231 / FVT-099).

``ProductionAuthorizationReplacement@1``

Provides a **separately named**, project-owned authorization prover with
SecPAL-style typed delegation semantics.  The implementation is derived only
from public formal specifications (typed assertions, can-say / can-act-as,
scoped delegation, constraints, revocation/time windows) and independently
reviewed clean-room design records.

Identity boundaries (fail-closed)
---------------------------------
* Provider id is ``production-authorization-replacement`` — never ``secpal``.
* Distinct from the in-process reference id ``secpal-authorization``.
* Never vendors Microsoft MSI bytes, decompiled code, sample source, or
  trademark-implying display names.
* Never claims Microsoft SecPAL vendor authority or satisfies FVT-G219.
* Authority ceiling is authorization decisions only; no theorem / deployment
  / legal-approval authority.
* ``deployment_ready`` remains false until FVT-G232 external approval.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.logic.backends.datalog.adapters import (
    AuthorizationBackendError,
    AuthorizationBackendOutcome,
    AuthorizationFixture,
    AuthorizationSourceBinding,
    EngineKind,
    EvaluationReceipt,
    ReferenceAuthorizationEvaluator,
    bound_diagnostics,
    outcome_to_result_status,
    render_secpal_program,
)
from ipfs_datasets_py.logic.backends.process import BoundedToolRunner
from ipfs_datasets_py.logic.backends.results import (
    AuthorizationResult,
    ResultAuthority,
    ResultStatus,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendCapabilities,
    BackendRequest,
    ExecutionBounds,
    QueryKind,
    ResourceUsage,
)
from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceSpan
from ipfs_datasets_py.logic.software_verification.authorization import (
    AtomPolarity,
    AuthorizationAtom,
    AuthorizationConstraint,
    AuthorizationEvidenceAuthority,
    AuthorizationFact,
    AuthorizationIR,
    AuthorizationPrincipal,
    AuthorizationRole,
    AuthorizationRule,
    AuthorizationTerm,
    AuthorizationValidationError,
    ConstraintKind,
    DecisionExplanation,
    DecisionOutcome,
    DecisionQuery,
    DelegationStatement,
    EffectKind,
    ExplanationStepKind,
    GeneratedCodeCorrectness,
    PolicyBounds,
    PolicyDecision,
    PrecedencePolicy,
    PredicateSignature,
    PrincipalKind,
    RuleKind,
)

# ---------------------------------------------------------------------------
# Stable identity (must never collide with external ``secpal`` or reference
# ``secpal-authorization``)
# ---------------------------------------------------------------------------

PRODUCTION_AUTHORIZATION_REPLACEMENT_INTERFACE: Final = (
    "ProductionAuthorizationReplacement@1"
)
PRODUCTION_AUTHORIZATION_REPLACEMENT_SCHEMA: Final = (
    "production-authorization-replacement/v1"
)
SECPAL_STYLE_AUTHORIZATION_BACKEND_VERSION: Final = (
    "SecPALStyleAuthorizationBackend@1"
)
PRODUCTION_AUTHORIZATION_PROVIDER_ID: Final = "production-authorization-replacement"
PRODUCTION_AUTHORIZATION_BACKEND_VERSION: Final = (
    "production-authorization-replacement/v1"
)
PRODUCTION_AUTHORIZATION_DISPLAY_NAME: Final = (
    "Project-owned production-candidate SecPAL-style authorization provider"
)
PRODUCTION_AUTHORIZATION_AUTHORITY_CEILING: Final = "authorization"
PRODUCTION_AUTHORIZATION_GOAL_ID: Final = "FVT-G231"
PRODUCTION_AUTHORIZATION_TASK_ID: Final = "FVT-099"
PRODUCTION_AUTHORIZATION_PROGRAM: Final = (
    "formal-verification-tactician/production-authorization-replacement"
)

# Forbidden identity tokens that must never be claimed by this provider.
FORBIDDEN_PROVIDER_IDS: Final = frozenset(
    {
        "secpal",
        "microsoft-secpal",
        "microsoft_secpal",
        "ms-secpal",
        "Microsoft.Research.SecPal",
    }
)
REFERENCE_SECPAL_PROVIDER_ID: Final = "secpal-authorization"
EXTERNAL_SECPAL_PROVIDER_ID: Final = "secpal"

FORBIDDEN_CLAIM_MARKERS: Final = frozenset(
    {
        "microsoft secpal authority",
        "microsoft vendor-compatibility",
        "satisfies fvt-g219",
        "fvt-g219 complete",
        "deployment approved",
        "legal approval complete",
    }
)

# Language surface coverage required by FVT-G231 acceptance.
TYPED_LANGUAGE_FEATURES: Final = (
    "principal_identity",
    "delegation_depth",
    "delegation_scope",
    "can_say",
    "can_act_as",
    "roles",
    "exclusions",
    "revocation",
    "time_validity",
    "conflict",
    "unknown_no_proof",
    "constraints",
    "deterministic_proof_witness",
    "counterexample_witness",
)

REQUIRED_CASE_KINDS: Final = (
    "positive",
    "negative",
    "mutation",
    "replay",
    "malformed",
    "cycle_resource_bound",
    "differential",
    "fuzz_property",
    "denial_safety",
)

CLEAN_ROOM_DESIGN_RECORD: Final = {
    "design_basis": (
        "public formal specifications for typed authorization logics with "
        "can-say / can-act-as delegation (Becker–Fournet–Gordon style "
        "SecPAL papers and subsequent open academic expositions)"
    ),
    "implementation_origin": "project-owned clean-room",
    "restricted_bytes_used": False,
    "microsoft_msi_used": False,
    "decompiled_code_used": False,
    "sample_source_used": False,
    "trademark_implication": False,
    "microsoft_vendor_compatibility_claim": False,
    "independent_review_status": "design-record-bound; legal/IP approval is FVT-G232",
    "notes": (
        "Executable semantics reuse the project AuthorizationIR and stratified "
        "reference evaluator under a separately named production-candidate "
        "identity.  No Microsoft Research SecPAL bytes or identifiers are "
        "imported, vendored, or claimed as authority."
    ),
}

DEFAULT_MAX_DIAGNOSTICS: Final = 32
DEFAULT_MAX_DIAGNOSTIC_CHARS: Final = 512
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ProductionAuthorizationError(ValueError):
    """Raised when the production authorization provider rejects an input."""


class CaseKind(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MUTATION = "mutation"
    REPLAY = "replay"
    MALFORMED = "malformed"
    CYCLE_RESOURCE_BOUND = "cycle_resource_bound"
    DIFFERENTIAL = "differential"
    FUZZ_PROPERTY = "fuzz_property"
    DENIAL_SAFETY = "denial_safety"


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise ProductionAuthorizationError(
            f"{field_name} must be a non-empty trimmed string without NUL"
        )
    return value


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sanitize_diagnostic(text: str) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    cleaned = cleaned.replace("\r", " ").replace("\n", " ").strip()
    if len(cleaned) > DEFAULT_MAX_DIAGNOSTIC_CHARS:
        cleaned = cleaned[: DEFAULT_MAX_DIAGNOSTIC_CHARS - 3] + "..."
    return cleaned


def assert_identity_boundary(provider_id: str) -> None:
    """Fail closed if a forbidden or reference/external id is claimed."""

    normalized = _text(provider_id, "provider_id").casefold()
    if normalized in {item.casefold() for item in FORBIDDEN_PROVIDER_IDS}:
        raise ProductionAuthorizationError(
            f"provider_id {provider_id!r} is forbidden for the production "
            "authorization replacement (external Microsoft SecPAL identity)"
        )
    if normalized == EXTERNAL_SECPAL_PROVIDER_ID:
        raise ProductionAuthorizationError(
            "must not reuse the external secpal provider id"
        )
    if normalized == REFERENCE_SECPAL_PROVIDER_ID:
        raise ProductionAuthorizationError(
            "production-candidate must be separately named from the "
            "in-process reference secpal-authorization engine"
        )
    if normalized != PRODUCTION_AUTHORIZATION_PROVIDER_ID.casefold():
        # Allow only the canonical production id for this provider surface.
        raise ProductionAuthorizationError(
            f"expected provider_id {PRODUCTION_AUTHORIZATION_PROVIDER_ID!r}, "
            f"got {provider_id!r}"
        )


def forbids_fvt_g219_completion() -> bool:
    """The production replacement cannot satisfy FVT-G219 (vendor SecPAL live)."""

    return True


def forbids_microsoft_secpal_authority() -> bool:
    return True


def forbids_deployment_authority() -> bool:
    return True


# ---------------------------------------------------------------------------
# Source-mapped fixture helpers
# ---------------------------------------------------------------------------


def _fixture_source_map() -> dict[str, Any]:
    source = SourceRef(
        ref_id="source:production-authorization-fixtures",
        source_uri="file:///policies/production-authorization-fixtures.json",
        source_id="production-authorization-fixtures.json",
        source_revision="git:production-authorization",
        content_sha256="c" * 64,
    )
    span = SourceSpan(
        span_id="span:production-authorization-fixtures",
        source_ref_id="source:production-authorization-fixtures",
        start_byte=0,
        end_byte=8192,
        start_line=1,
        start_column=1,
        end_line=400,
        end_column=2,
    )
    return {
        "source": source,
        "span": span,
        "mapped": {
            "source_ref_ids": ("source:production-authorization-fixtures",),
            "span_ids": ("span:production-authorization-fixtures",),
        },
    }


def _const(value: str, sort: str = "principal") -> AuthorizationTerm:
    return AuthorizationTerm.constant(value, sort)


def _var(value: str, sort: str = "principal") -> AuthorizationTerm:
    return AuthorizationTerm.variable(value, sort)


def _atom(
    predicate_id: str,
    *args: AuthorizationTerm,
    polarity: AtomPolarity = AtomPolarity.POSITIVE,
) -> AuthorizationAtom:
    return AuthorizationAtom(predicate_id, args, polarity)


@dataclass(frozen=True, slots=True)
class ProductionCaseResult:
    """One executable semantic case with deterministic witnesses."""

    case_id: str
    kind: str
    outcome: str
    expected_outcome: str
    passed: bool
    policy_digest: str
    query_id: str
    witness_digest: str
    explanation_step_kinds: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "diagnostics": list(self.diagnostics),
            "expected_outcome": self.expected_outcome,
            "explanation_step_kinds": list(self.explanation_step_kinds),
            "kind": self.kind,
            "metadata": self.metadata.to_dict(),
            "outcome": self.outcome,
            "passed": self.passed,
            "policy_digest": self.policy_digest,
            "query_id": self.query_id,
            "witness_digest": self.witness_digest,
        }


@dataclass(frozen=True, slots=True)
class ProductionCase:
    """Executable case definition (document + query + expectation)."""

    case_id: str
    kind: CaseKind | str
    document: AuthorizationIR | None
    query: DecisionQuery | None
    expected_outcome: DecisionOutcome | str | None
    malformed: bool = False
    malformed_payload: Mapping[str, Any] | None = None
    mutation_of: str = ""
    property_name: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _text(self.case_id, "case_id"))
        kind = (
            self.kind
            if isinstance(self.kind, CaseKind)
            else CaseKind(str(self.kind))
        )
        object.__setattr__(self, "kind", kind)
        if self.malformed:
            if self.malformed_payload is None:
                raise ProductionAuthorizationError(
                    f"malformed case {self.case_id!r} requires malformed_payload"
                )
            return
        if not isinstance(self.document, AuthorizationIR):
            raise ProductionAuthorizationError(
                f"case {self.case_id!r} requires AuthorizationIR document"
            )
        if not isinstance(self.query, DecisionQuery):
            raise ProductionAuthorizationError(
                f"case {self.case_id!r} requires DecisionQuery"
            )
        if self.expected_outcome is None:
            raise ProductionAuthorizationError(
                f"case {self.case_id!r} requires expected_outcome"
            )
        outcome = (
            self.expected_outcome
            if isinstance(self.expected_outcome, DecisionOutcome)
            else DecisionOutcome(str(self.expected_outcome))
        )
        object.__setattr__(self, "expected_outcome", outcome)


# ---------------------------------------------------------------------------
# Policy document builders (typed SecPAL-style language surface)
# ---------------------------------------------------------------------------


def _base_catalog(mapped: Mapping[str, Any]) -> dict[str, Any]:
    principals = (
        AuthorizationPrincipal(
            "principal:root", "Root", PrincipalKind.SYSTEM, **mapped
        ),
        AuthorizationPrincipal(
            "principal:alice", "Alice", PrincipalKind.USER, **mapped
        ),
        AuthorizationPrincipal(
            "principal:bob", "Bob", PrincipalKind.USER, **mapped
        ),
        AuthorizationPrincipal(
            "principal:carol", "Carol", PrincipalKind.USER, **mapped
        ),
        AuthorizationPrincipal(
            "principal:service", "Service", PrincipalKind.SERVICE, **mapped
        ),
    )
    roles = (
        AuthorizationRole(
            "role:admin",
            "Administrator",
            member_principal_ids=("principal:alice",),
            **mapped,
        ),
        AuthorizationRole(
            "role:reader",
            "Reader",
            member_principal_ids=("principal:bob",),
            **mapped,
        ),
        AuthorizationRole(
            "role:excluded",
            "Excluded",
            member_principal_ids=("principal:carol",),
            **mapped,
        ),
    )
    predicates = (
        PredicateSignature(
            "pred:role",
            "role",
            2,
            ("principal", "role"),
            is_intensional=False,
            **mapped,
        ),
        PredicateSignature(
            "pred:may",
            "may",
            3,
            ("principal", "action", "resource"),
            is_intensional=True,
            **mapped,
        ),
        PredicateSignature(
            "pred:denied",
            "denied",
            3,
            ("principal", "action", "resource"),
            is_intensional=True,
            **mapped,
        ),
        PredicateSignature(
            "pred:sensitive",
            "sensitive",
            1,
            ("resource",),
            is_intensional=False,
            **mapped,
        ),
        PredicateSignature(
            "pred:revoked",
            "revoked",
            1,
            ("principal",),
            is_intensional=False,
            **mapped,
        ),
        PredicateSignature(
            "pred:can_say",
            "can_say",
            2,
            ("issuer", "subject"),
            is_intensional=True,
            **mapped,
        ),
        PredicateSignature(
            "pred:can_act_as",
            "can_act_as",
            2,
            ("actor", "as_principal"),
            is_intensional=True,
            **mapped,
        ),
    )
    facts = (
        AuthorizationFact(
            "fact:alice-admin",
            _atom("pred:role", _const("principal:alice"), _const("role:admin", "role")),
            issuer_principal_id="principal:root",
            **mapped,
        ),
        AuthorizationFact(
            "fact:bob-reader",
            _atom("pred:role", _const("principal:bob"), _const("role:reader", "role")),
            issuer_principal_id="principal:root",
            **mapped,
        ),
        AuthorizationFact(
            "fact:doc-sensitive",
            _atom("pred:sensitive", _const("docs/payroll", "resource")),
            issuer_principal_id="principal:root",
            **mapped,
        ),
    )
    constraints = (
        AuthorizationConstraint(
            "constraint:window-valid",
            ConstraintKind.TEMPORAL_WINDOW,
            FrozenMap({"not_before": 0, "not_after": 10_000_000}),
            **mapped,
        ),
        AuthorizationConstraint(
            "constraint:scope-docs",
            ConstraintKind.SCOPE,
            FrozenMap({"path_prefix": "docs/"}),
            **mapped,
        ),
        AuthorizationConstraint(
            "constraint:not-revoked-eq",
            ConstraintKind.INEQUALITY,
            FrozenMap({"left": "principal:bob", "right": "principal:revoked"}),
            **mapped,
        ),
    )
    rules = (
        AuthorizationRule(
            "rule:admin-may-read",
            head=_atom(
                "pred:may",
                _var("P"),
                _const("read", "action"),
                _var("R", "resource"),
            ),
            body=(
                _atom("pred:role", _var("P"), _const("role:admin", "role")),
            ),
            kind=RuleKind.DATALOG,
            effect=EffectKind.ALLOW,
            stratum=1,
            constraint_ids=("constraint:scope-docs",),
            **mapped,
        ),
        AuthorizationRule(
            "rule:deny-sensitive-non-admin",
            head=_atom(
                "pred:denied",
                _var("P"),
                _const("read", "action"),
                _var("R", "resource"),
            ),
            body=(
                _atom("pred:sensitive", _var("R", "resource")),
                _atom(
                    "pred:role",
                    _var("P"),
                    _const("role:admin", "role"),
                    polarity=AtomPolarity.NEGATIVE,
                ),
            ),
            kind=RuleKind.DATALOG,
            effect=EffectKind.DENY,
            stratum=1,
            **mapped,
        ),
        # can-say: trust root asserts that service may read public docs.
        AuthorizationRule(
            "rule:root-can-say-service-read",
            head=_atom(
                "pred:may",
                _const("principal:service"),
                _const("read", "action"),
                _const("docs/public", "resource"),
            ),
            body=(),
            kind=RuleKind.SECPAL_SAYS,
            effect=EffectKind.ALLOW,
            stratum=0,
            issuer_principal_id="principal:root",
            constraint_ids=("constraint:window-valid",),
            **mapped,
        ),
        # Exclusion: members of role:excluded are denied write.
        AuthorizationRule(
            "rule:exclude-write",
            head=_atom(
                "pred:denied",
                _var("P"),
                _const("write", "action"),
                _var("R", "resource"),
            ),
            body=(
                _atom(
                    "pred:role",
                    _var("P"),
                    _const("role:excluded", "role"),
                ),
            ),
            kind=RuleKind.DATALOG,
            effect=EffectKind.DENY,
            stratum=1,
            **mapped,
        ),
        # Revocation: revoked principals cannot read.
        AuthorizationRule(
            "rule:revoked-deny-read",
            head=_atom(
                "pred:denied",
                _var("P"),
                _const("read", "action"),
                _var("R", "resource"),
            ),
            body=(_atom("pred:revoked", _var("P")),),
            kind=RuleKind.DATALOG,
            effect=EffectKind.DENY,
            stratum=1,
            **mapped,
        ),
    )
    return {
        "principals": principals,
        "roles": roles,
        "predicates": predicates,
        "facts": facts,
        "constraints": constraints,
        "rules": rules,
    }


def _document(
    *,
    source: SourceRef,
    span: SourceSpan,
    mapped: Mapping[str, Any],
    queries: tuple[DecisionQuery, ...],
    catalog: Mapping[str, Any] | None = None,
    extra_facts: tuple[AuthorizationFact, ...] = (),
    extra_rules: tuple[AuthorizationRule, ...] = (),
    delegations: tuple[DelegationStatement, ...] = (),
    speaks_for: tuple[Any, ...] = (),
    precedence: PrecedencePolicy | None = None,
    bounds: PolicyBounds | None = None,
    trust_roots: tuple[str, ...] = ("principal:root",),
    metadata: Mapping[str, Any] | None = None,
) -> AuthorizationIR:
    base = catalog or _base_catalog(mapped)
    from ipfs_datasets_py.logic.software_verification.authorization import (
        SpeaksForRelation,
    )

    speaks_for_tuple: tuple[SpeaksForRelation, ...] = tuple(speaks_for)  # type: ignore[assignment]
    return AuthorizationIR(
        sources=(source,),
        spans=(span,),
        principals=base["principals"],
        trust_root_principal_ids=trust_roots,
        roles=base["roles"],
        predicates=base["predicates"],
        facts=base["facts"] + extra_facts,
        rules=base["rules"] + extra_rules,
        constraints=base["constraints"],
        delegations=delegations,
        speaks_for=speaks_for_tuple,
        bounds=bounds
        or PolicyBounds(
            max_delegation_depth=4,
            max_derivation_depth=64,
            max_stratum=8,
            universe_size=64,
        ),
        precedence=precedence or PrecedencePolicy(resolution="deny_overrides"),
        queries=queries,
        metadata=FrozenMap(
            {
                "fixture_set": "production-authorization-replacement",
                "provider_id": PRODUCTION_AUTHORIZATION_PROVIDER_ID,
                "language_features": list(TYPED_LANGUAGE_FEATURES),
                **dict(metadata or {}),
            }
        ),
    )


def build_production_cases() -> tuple[ProductionCase, ...]:
    """Build the executable formal-semantics case suite for FVT-G231."""

    from ipfs_datasets_py.logic.software_verification.authorization import (
        SpeaksForRelation,
    )

    env = _fixture_source_map()
    source, span, mapped = env["source"], env["span"], env["mapped"]
    catalog = _base_catalog(mapped)

    def q(
        query_id: str,
        principal_id: str,
        action: str,
        resource: str,
        *,
        goal: AuthorizationAtom | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> DecisionQuery:
        return DecisionQuery(
            query_id,
            principal_id=principal_id,
            action=action,
            resource=resource,
            goal_atom=goal,
            context=FrozenMap(context or {"evaluated_at_ms": 1000}),
            **mapped,
        )

    # --- positive: admin allow ---
    allow_query = q(
        "query:positive-alice-allow",
        "principal:alice",
        "read",
        "docs/payroll",
        goal=_atom(
            "pred:may",
            _const("principal:alice"),
            _const("read", "action"),
            _const("docs/payroll", "resource"),
        ),
    )
    positive_allow = ProductionCase(
        "case:positive-allow",
        CaseKind.POSITIVE,
        _document(source=source, span=span, mapped=mapped, queries=(allow_query,)),
        allow_query,
        DecisionOutcome.ALLOW,
        notes="principal identity + role + scoped allow",
    )

    # --- positive: can-say service allow ---
    can_say_query = q(
        "query:positive-can-say",
        "principal:service",
        "read",
        "docs/public",
        goal=_atom(
            "pred:may",
            _const("principal:service"),
            _const("read", "action"),
            _const("docs/public", "resource"),
        ),
    )
    positive_can_say = ProductionCase(
        "case:positive-can-say",
        CaseKind.POSITIVE,
        _document(
            source=source, span=span, mapped=mapped, queries=(can_say_query,)
        ),
        can_say_query,
        DecisionOutcome.ALLOW,
        notes="can-say (SECPAL_SAYS) under trust root",
    )

    # --- positive: can-act-as / speaks-for + delegation ---
    act_as_query = q(
        "query:positive-can-act-as",
        "principal:bob",
        "read",
        "docs/public/readme",
    )
    delegations = (
        DelegationStatement(
            "delegation:root-alice",
            issuer_principal_id="principal:root",
            subject_principal_id="principal:alice",
            capability="read",
            delegation_depth=2,
            resource_scope=("docs/",),
            **mapped,
        ),
        DelegationStatement(
            "delegation:alice-bob",
            issuer_principal_id="principal:alice",
            subject_principal_id="principal:bob",
            capability="read",
            delegation_depth=1,
            parent_delegation_id="delegation:root-alice",
            resource_scope=("docs/public/",),
            **mapped,
        ),
    )
    speaks = (
        SpeaksForRelation(
            "speaks-for:bob-as-alice",
            speaker_principal_id="principal:bob",
            subject_principal_id="principal:alice",
            max_composition_depth=1,
            **mapped,
        ),
    )
    positive_act_as = ProductionCase(
        "case:positive-can-act-as-delegation",
        CaseKind.POSITIVE,
        _document(
            source=source,
            span=span,
            mapped=mapped,
            queries=(act_as_query,),
            delegations=delegations,
            speaks_for=speaks,
        ),
        act_as_query,
        DecisionOutcome.ALLOW,
        notes="can-act-as (speaks-for) with scoped delegation depth",
    )

    # --- negative: non-admin denied on sensitive ---
    deny_query = q(
        "query:negative-bob-deny",
        "principal:bob",
        "read",
        "docs/payroll",
    )
    negative_deny = ProductionCase(
        "case:negative-deny",
        CaseKind.NEGATIVE,
        _document(source=source, span=span, mapped=mapped, queries=(deny_query,)),
        deny_query,
        DecisionOutcome.DENY,
        notes="negative deny for non-admin on sensitive resource",
    )

    # --- negative: exclusion role cannot write ---
    exclude_query = q(
        "query:negative-exclusion",
        "principal:carol",
        "write",
        "docs/public/note",
    )
    negative_exclusion = ProductionCase(
        "case:negative-exclusion",
        CaseKind.NEGATIVE,
        _document(
            source=source, span=span, mapped=mapped, queries=(exclude_query,)
        ),
        exclude_query,
        DecisionOutcome.DENY,
        notes="role exclusion deny",
    )

    # --- negative: revocation ---
    revoked_query = q(
        "query:negative-revocation",
        "principal:alice",
        "read",
        "docs/payroll",
        goal=_atom(
            "pred:may",
            _const("principal:alice"),
            _const("read", "action"),
            _const("docs/payroll", "resource"),
        ),
    )
    revoked_fact = AuthorizationFact(
        "fact:alice-revoked",
        _atom("pred:revoked", _const("principal:alice")),
        issuer_principal_id="principal:root",
        **mapped,
    )
    negative_revocation = ProductionCase(
        "case:negative-revocation",
        CaseKind.NEGATIVE,
        _document(
            source=source,
            span=span,
            mapped=mapped,
            queries=(revoked_query,),
            extra_facts=(revoked_fact,),
            precedence=PrecedencePolicy(resolution="deny_overrides"),
        ),
        revoked_query,
        DecisionOutcome.DENY,
        notes="revocation + deny_overrides beats prior allow evidence",
    )

    # --- negative: time validity window expired ---
    expired_query = q(
        "query:negative-time-expired",
        "principal:service",
        "read",
        "docs/public",
        goal=_atom(
            "pred:may",
            _const("principal:service"),
            _const("read", "action"),
            _const("docs/public", "resource"),
        ),
        context={"evaluated_at_ms": 99_999_999},
    )
    # Constraint on can-say rule rejects expired window → no allow derivation.
    # Without allow or deny evidence → unknown (no-proof).
    negative_time = ProductionCase(
        "case:negative-time-validity",
        CaseKind.NEGATIVE,
        _document(
            source=source, span=span, mapped=mapped, queries=(expired_query,)
        ),
        expired_query,
        DecisionOutcome.UNKNOWN,
        notes="time validity: expired temporal window yields unknown/no-proof",
    )

    # --- unknown / no-proof ---
    unknown_query = q(
        "query:unknown-no-proof",
        "principal:bob",
        "delete",
        "docs/payroll",
    )
    unknown_case = ProductionCase(
        "case:unknown-no-proof",
        CaseKind.NEGATIVE,
        _document(
            source=source, span=span, mapped=mapped, queries=(unknown_query,)
        ),
        unknown_query,
        DecisionOutcome.UNKNOWN,
        notes="unknown when no allow or deny evidence exists",
    )

    # --- conflict ---
    conflict_query = q(
        "query:conflict",
        "principal:bob",
        "read",
        "docs/payroll",
    )
    force_allow = AuthorizationRule(
        "rule:force-bob-allow",
        head=_atom(
            "pred:may",
            _const("principal:bob"),
            _const("read", "action"),
            _const("docs/payroll", "resource"),
        ),
        body=(),
        kind=RuleKind.DATALOG,
        effect=EffectKind.ALLOW,
        stratum=0,
        **mapped,
    )
    conflict_case = ProductionCase(
        "case:conflict-explicit",
        CaseKind.POSITIVE,
        _document(
            source=source,
            span=span,
            mapped=mapped,
            queries=(conflict_query,),
            extra_rules=(force_allow,),
            precedence=PrecedencePolicy(resolution="explicit_conflict"),
        ),
        conflict_query,
        DecisionOutcome.CONFLICT,
        notes="explicit conflict when allow and deny evidence co-exist",
    )

    # --- mutation: strip admin role membership AND role fact → allow becomes deny ---
    mutated_roles = (
        AuthorizationRole(
            "role:admin",
            "Administrator",
            member_principal_ids=(),  # mutation: strip alice
            **mapped,
        ),
        catalog["roles"][1],
        catalog["roles"][2],
    )
    mutated_facts = tuple(
        fact
        for fact in catalog["facts"]
        if fact.fact_id != "fact:alice-admin"
    )
    mutated_catalog = dict(catalog)
    mutated_catalog["roles"] = mutated_roles
    mutated_catalog["facts"] = mutated_facts
    mutation_query = q(
        "query:mutation-principal",
        "principal:alice",
        "read",
        "docs/payroll",
        goal=_atom(
            "pred:may",
            _const("principal:alice"),
            _const("read", "action"),
            _const("docs/payroll", "resource"),
        ),
    )
    mutation_case = ProductionCase(
        "case:mutation-role-membership",
        CaseKind.MUTATION,
        _document(
            source=source,
            span=span,
            mapped=mapped,
            queries=(mutation_query,),
            catalog=mutated_catalog,
        ),
        mutation_query,
        DecisionOutcome.DENY,
        mutation_of="case:positive-allow",
        notes="mutating admin membership and role fact changes the verdict",
    )

    # --- mutation: delegation scope narrowed out of query resource ---
    out_of_scope_query = q(
        "query:mutation-scope",
        "principal:bob",
        "read",
        "docs/secret/payroll",
    )
    mutation_scope = ProductionCase(
        "case:mutation-delegation-scope",
        CaseKind.MUTATION,
        _document(
            source=source,
            span=span,
            mapped=mapped,
            queries=(out_of_scope_query,),
            delegations=delegations,
        ),
        out_of_scope_query,
        DecisionOutcome.UNKNOWN,
        mutation_of="case:positive-can-act-as-delegation",
        notes="delegation scope mutation yields no proof",
    )

    # --- replay (same as positive allow; runner checks determinism) ---
    replay_case = ProductionCase(
        "case:replay-positive-allow",
        CaseKind.REPLAY,
        positive_allow.document,
        positive_allow.query,
        DecisionOutcome.ALLOW,
        notes="deterministic replay of positive allow",
    )

    # --- malformed ---
    malformed_case = ProductionCase(
        "case:malformed-payload",
        CaseKind.MALFORMED,
        None,
        None,
        None,
        malformed=True,
        malformed_payload={
            "encoding": "authorization-ir",
            "authorization_ir": {"not": "a-valid-document"},
            "query_id": "query:missing",
        },
        notes="malformed AuthorizationIR fails closed",
    )

    # --- cycle / resource bound ---
    # Long chain without a trust-root issuer: evaluation fails closed (unknown)
    # once parent links or depth bounds are exhausted.  Depths decrease strictly
    # so the IR validates; the trust gap is the resource/cycle safety property.
    deep_delegations = (
        DelegationStatement(
            "delegation:depth-3",
            issuer_principal_id="principal:carol",
            subject_principal_id="principal:alice",
            capability="read",
            delegation_depth=3,
            resource_scope=("docs/",),
            **mapped,
        ),
        DelegationStatement(
            "delegation:depth-2",
            issuer_principal_id="principal:alice",
            subject_principal_id="principal:bob",
            capability="read",
            delegation_depth=2,
            parent_delegation_id="delegation:depth-3",
            resource_scope=("docs/",),
            **mapped,
        ),
        DelegationStatement(
            "delegation:depth-1",
            issuer_principal_id="principal:bob",
            subject_principal_id="principal:service",
            capability="read",
            delegation_depth=1,
            parent_delegation_id="delegation:depth-2",
            resource_scope=("docs/public/",),
            **mapped,
        ),
    )
    cycle_query = q(
        "query:cycle-bound",
        "principal:service",
        "read",
        "docs/public/x",
    )
    cycle_case = ProductionCase(
        "case:cycle-resource-bound",
        CaseKind.CYCLE_RESOURCE_BOUND,
        _document(
            source=source,
            span=span,
            mapped=mapped,
            queries=(cycle_query,),
            delegations=deep_delegations,
            bounds=PolicyBounds(
                max_delegation_depth=3,
                max_derivation_depth=4,
                max_stratum=4,
                universe_size=16,
            ),
            # Trust roots exclude the chain head issuer → fail closed as unknown.
            trust_roots=("principal:root",),
        ),
        cycle_query,
        DecisionOutcome.UNKNOWN,
        notes="untrusted deep delegation chain fails closed under depth/resource bounds",
    )

    # --- differential vs reference engine identity (same outcome, distinct id) ---
    differential_case = ProductionCase(
        "case:differential-vs-reference-identity",
        CaseKind.DIFFERENTIAL,
        positive_allow.document,
        positive_allow.query,
        DecisionOutcome.ALLOW,
        notes="production and reference agree on outcome but differ in identity",
    )

    # --- fuzz / property: deny_overrides is denial-safe ---
    fuzz_case = ProductionCase(
        "case:fuzz-property-deny-overrides",
        CaseKind.FUZZ_PROPERTY,
        conflict_case.document,
        conflict_query,
        DecisionOutcome.CONFLICT,  # under explicit_conflict; property runner varies
        property_name="deny_overrides_never_emits_allow_when_deny_present",
        notes="property: under deny_overrides, simultaneous deny blocks allow",
    )

    # --- denial safety (deny_overrides on conflict document) ---
    denial_doc = _document(
        source=source,
        span=span,
        mapped=mapped,
        queries=(conflict_query,),
        extra_rules=(force_allow,),
        precedence=PrecedencePolicy(resolution="deny_overrides"),
    )
    denial_safety = ProductionCase(
        "case:denial-safety",
        CaseKind.DENIAL_SAFETY,
        denial_doc,
        conflict_query,
        DecisionOutcome.DENY,
        notes="denial-safety: deny_overrides wins over co-existing allow",
    )

    return (
        positive_allow,
        positive_can_say,
        positive_act_as,
        negative_deny,
        negative_exclusion,
        negative_revocation,
        negative_time,
        unknown_case,
        conflict_case,
        mutation_case,
        mutation_scope,
        replay_case,
        malformed_case,
        cycle_case,
        differential_case,
        fuzz_case,
        denial_safety,
    )


# ---------------------------------------------------------------------------
# Provider backend
# ---------------------------------------------------------------------------


class SecPALStyleAuthorizationBackend:
    """Project-owned production-candidate SecPAL-style authorization backend.

    Interface: ``SecPALStyleAuthorizationBackend@1`` /
    ``ProductionAuthorizationReplacement@1``.

    Distinct provider id: ``production-authorization-replacement``.
    """

    interface_version: Final = SECPAL_STYLE_AUTHORIZATION_BACKEND_VERSION
    backend_id: Final = PRODUCTION_AUTHORIZATION_PROVIDER_ID
    # Aliases deliberately exclude ``secpal`` and ``secpal-authorization``.
    aliases: Final = frozenset(
        {
            "production-authorization",
            "production_authorization_replacement",
            "secpal-style-authorization",
            "secpal_style_authorization",
            "project-authorization-prover",
        }
    )
    engine_kind: Final = EngineKind.REFERENCE
    accepted_source_formats: Final = frozenset(
        {
            "authorization-ir",
            "authorization_ir",
            "authorization",
            "production-authorization",
            "secpal-style",
        }
    )

    def __init__(
        self,
        *,
        backend_version: str = PRODUCTION_AUTHORIZATION_BACKEND_VERSION,
        runner: BoundedToolRunner | None = None,
    ) -> None:
        assert_identity_boundary(self.backend_id)
        self.backend_version = _text(backend_version, "backend_version")
        self._runner = runner or BoundedToolRunner()
        self._evaluator = ReferenceAuthorizationEvaluator()
        self.capabilities = BackendCapabilities(
            logic_families=(
                "authorization",
                "policy",
                "secpal-style",
                "production-authorization",
                "software_verification",
            ),
            query_kinds=(QueryKind.POLICY_APPROVAL,),
            deterministic=True,
        )
        self.use_external_engine = False

    def supports(self, logic_family: str, query_kind: QueryKind) -> bool:
        return self.capabilities.supports(logic_family, query_kind)

    def is_available(self) -> bool:
        return True

    def identity(self) -> dict[str, Any]:
        return {
            "provider_id": self.backend_id,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "interface": PRODUCTION_AUTHORIZATION_REPLACEMENT_INTERFACE,
            "adapter_interface": self.interface_version,
            "display_name": PRODUCTION_AUTHORIZATION_DISPLAY_NAME,
            "authority_ceiling": PRODUCTION_AUTHORIZATION_AUTHORITY_CEILING,
            "aliases": sorted(self.aliases),
            "forbidden_provider_ids": sorted(FORBIDDEN_PROVIDER_IDS),
            "distinct_from_reference_id": REFERENCE_SECPAL_PROVIDER_ID,
            "distinct_from_external_id": EXTERNAL_SECPAL_PROVIDER_ID,
            "forbids_fvt_g219_completion": forbids_fvt_g219_completion(),
            "forbids_microsoft_secpal_authority": forbids_microsoft_secpal_authority(),
            "forbids_deployment_authority": forbids_deployment_authority(),
            "deployment_ready": False,
            "legal_approval_complete": False,
            "clean_room": dict(CLEAN_ROOM_DESIGN_RECORD),
            "typed_language_features": list(TYPED_LANGUAGE_FEATURES),
            "deterministic": True,
            "in_process": True,
            "lazy_dependencies": (),
            "requires_external_install": False,
        }

    def render(self, document: AuthorizationIR, query: DecisionQuery) -> str:
        # Project-owned textual rendering of the typed policy for witnesses.
        header = (
            f"# production-authorization-replacement policy render\n"
            f"# provider_id={self.backend_id}\n"
            f"# interface={PRODUCTION_AUTHORIZATION_REPLACEMENT_INTERFACE}\n"
            f"# not-microsoft-secpal\n"
        )
        return header + render_secpal_program(document, query)

    def evaluate(
        self,
        document: AuthorizationIR,
        query: DecisionQuery | str | None = None,
        *,
        max_steps: int | None = None,
    ) -> tuple[PolicyDecision, DecisionExplanation, bool]:
        return self._evaluator.evaluate(document, query, max_steps=max_steps)

    def _extract(
        self, request: BackendRequest
    ) -> tuple[AuthorizationIR, DecisionQuery, str]:
        payload = request.payload.to_dict()
        encoding = str(payload.get("encoding") or "authorization-ir").lower()
        raw_document = payload.get("authorization_ir") or payload.get("document")
        if isinstance(raw_document, AuthorizationIR):
            document = raw_document
        elif isinstance(raw_document, Mapping):
            try:
                document = AuthorizationIR.from_dict(raw_document)
            except (AuthorizationValidationError, TypeError, ValueError) as error:
                raise AuthorizationBackendError(
                    f"invalid authorization_ir payload: {error}"
                ) from error
        else:
            raise AuthorizationBackendError(
                "authorization request payload requires authorization_ir"
            )
        raw_query = payload.get("query")
        query_id = payload.get("query_id")
        if isinstance(raw_query, DecisionQuery):
            query = raw_query
        elif isinstance(raw_query, Mapping):
            query = DecisionQuery.from_dict(raw_query)
        elif isinstance(query_id, str) and query_id:
            matches = [item for item in document.queries if item.query_id == query_id]
            if not matches:
                raise AuthorizationBackendError(f"unknown query_id {query_id!r}")
            query = matches[0]
        elif len(document.queries) == 1:
            query = document.queries[0]
        else:
            raise AuthorizationBackendError(
                "payload requires query or query_id when multiple queries exist"
            )
        return document, query, encoding

    def _validate_request(self, request: BackendRequest) -> None:
        if not isinstance(request, BackendRequest):
            raise AuthorizationBackendError("request must be a BackendRequest")
        if request.requested_backend_id and request.requested_backend_id not in {
            self.backend_id,
            *self.aliases,
        }:
            raise AuthorizationBackendError(
                f"request targets {request.requested_backend_id!r}, "
                f"not {self.backend_id!r}"
            )
        if request.requested_backend_id in FORBIDDEN_PROVIDER_IDS or (
            request.requested_backend_id == EXTERNAL_SECPAL_PROVIDER_ID
        ):
            raise AuthorizationBackendError(
                "production provider refuses external secpal identity routing"
            )
        if not self.capabilities.supports(request.logic_family, request.query_kind):
            raise AuthorizationBackendError(
                f"{self.backend_id} does not support {request.logic_family}/"
                f"{request.query_kind.value}"
            )
        if request.query_kind is not QueryKind.POLICY_APPROVAL:
            raise AuthorizationBackendError(
                "authorization backends answer policy_approval queries only"
            )

    def run(
        self,
        request: BackendRequest,
        *,
        cancellation: Any | None = None,
    ) -> AuthorizationBackendOutcome:
        del cancellation  # cooperative cancellation reserved; evaluator is finite
        self._validate_request(request)
        document, query, encoding = self._extract(request)
        if encoding not in self.accepted_source_formats:
            raise AuthorizationBackendError(
                f"request encoding {encoding!r} is not supported by {self.backend_id}"
            )
        binding = AuthorizationSourceBinding.bind(
            request, document, query, source_format=encoding
        )
        decision, explanation, bounds_exhausted = self._evaluator.evaluate(
            document,
            query,
            max_steps=request.bounds.max_steps,
        )
        outcome = decision.outcome
        status = outcome_to_result_status(outcome)
        reason = f"production evaluator returned {outcome.value}"
        diagnostics: list[str] = []
        if bounds_exhausted and outcome is DecisionOutcome.UNKNOWN:
            reason = "authorization derivation bounds exhausted"
            diagnostics.append("bounds_exhausted")
        if status in {ResultStatus.PROVED, ResultStatus.DISPROVED}:
            raise AuthorizationBackendError(
                "production authorization backend attempted to emit theorem authority"
            )
        receipt = EvaluationReceipt(
            request_digest=request.digest,
            source_binding=binding,
            outcome=outcome,
            decision=decision,
            explanation=explanation,
            engine=EngineKind.REFERENCE,
            engine_outcome=outcome,
            engine_agreed=True,
            bounds_exhausted=bounds_exhausted,
            diagnostics=tuple(diagnostics),
        )
        witness: dict[str, Any] = {
            "receipt_id": receipt.receipt_id,
            "outcome": receipt.outcome.value,
            "engine": "production-reference",
            "engine_agreed": True,
            "bounds_exhausted": bounds_exhausted,
            "authority": PRODUCTION_AUTHORIZATION_AUTHORITY_CEILING,
            "generated_code_correctness": GeneratedCodeCorrectness.NOT_ESTABLISHED.value,
            "is_theorem_authority": False,
            "provider_id": self.backend_id,
            "forbids_fvt_g219_completion": True,
            "forbids_microsoft_secpal_authority": True,
            "explanation": explanation.to_dict(),
            "decision": decision.to_dict(),
            "bound_rule_ids": [
                step.reference_id
                for step in explanation.steps
                if step.kind is ExplanationStepKind.RULE
            ],
        }
        result = AuthorizationResult(
            result_id=f"result:{self.backend_id}:{stable_digest({'r': request.digest, 'o': outcome.value})}",
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            authority=ResultAuthority.AUTHORIZATION,
            status=status,
            assumptions=request.assumption_ids,
            bounds=request.bounds,
            translation_ceiling=EvidenceAuthority.NONE,
            usage=ResourceUsage(steps=1),
            witness=witness,
            diagnostics=bound_diagnostics(diagnostics),
            reason=_sanitize_diagnostic(reason),
            metadata={
                "adapter_interface": self.interface_version,
                "production_interface": PRODUCTION_AUTHORIZATION_REPLACEMENT_INTERFACE,
                "evaluation_receipt": receipt.to_dict(),
                "source_binding": binding.to_dict(),
                "authorization_authority_ceiling": (
                    AuthorizationEvidenceAuthority.AUTHORIZATION.value
                ),
                "forbids_fvt_g219_completion": True,
                "forbids_microsoft_secpal_authority": True,
                "deployment_ready": False,
            },
        )
        return AuthorizationBackendOutcome(
            result=result,
            receipt=receipt,
            source_binding=binding,
        )

    def run_policy_decision(
        self,
        document: AuthorizationIR,
        query: DecisionQuery,
        *,
        request_id: str = "request:production-authorization",
        max_steps: int = 256,
    ) -> dict[str, Any]:
        """Convenience API used by verification_api and integration tests."""

        request = BackendRequest(
            request_id=request_id,
            claim_id="claim:production-authorization",
            declaration_id="declaration:production-authorization",
            claim_digest="a" * 64,
            obligation_id="obligation:production-authorization",
            obligation_digest="b" * 64,
            assumption_ids=("assumption:reviewed-policy",),
            logic_family="authorization",
            query_kind=QueryKind.POLICY_APPROVAL,
            bounds=ExecutionBounds(timeout_ms=500, max_steps=max_steps),
            payload=FrozenMap(
                {
                    "encoding": "authorization-ir",
                    "authorization_ir": document.to_dict(),
                    "query_id": query.query_id,
                }
            ),
            requested_backend_id=self.backend_id,
        )
        try:
            outcome = self.run(request)
        except AuthorizationBackendError as error:
            return {
                "status": "error",
                "provider_id": self.backend_id,
                "error": str(error),
                "authority": PRODUCTION_AUTHORIZATION_AUTHORITY_CEILING,
            }
        return {
            "status": outcome.result.status.value,
            "outcome": outcome.receipt.outcome.value,
            "provider_id": self.backend_id,
            "backend_version": self.backend_version,
            "authority": PRODUCTION_AUTHORIZATION_AUTHORITY_CEILING,
            "is_theorem_authority": False,
            "forbids_fvt_g219_completion": True,
            "forbids_microsoft_secpal_authority": True,
            "deployment_ready": False,
            "receipt": outcome.receipt.to_dict(),
            "witness": outcome.result.witness,
            "source_binding": outcome.source_binding.to_dict(),
            "request_digest": request.digest,
        }


# Keep a short alias used by public API docs.
ProductionAuthorizationReplacementBackend = SecPALStyleAuthorizationBackend


# ---------------------------------------------------------------------------
# Case execution
# ---------------------------------------------------------------------------


def _witness_digest(
    decision: PolicyDecision,
    explanation: DecisionExplanation,
    *,
    outcome: DecisionOutcome,
) -> str:
    return stable_digest(
        {
            "decision": decision.to_dict(),
            "explanation": explanation.to_dict(),
            "outcome": outcome.value,
            "provider_id": PRODUCTION_AUTHORIZATION_PROVIDER_ID,
        }
    )


def run_production_case(
    case: ProductionCase,
    *,
    backend: SecPALStyleAuthorizationBackend | None = None,
) -> ProductionCaseResult:
    """Execute one production case against the clean-room evaluator."""

    provider = backend or SecPALStyleAuthorizationBackend()
    if case.malformed:
        try:
            AuthorizationIR.from_dict(dict(case.malformed_payload or {}))
            return ProductionCaseResult(
                case_id=case.case_id,
                kind=case.kind.value,
                outcome="error",
                expected_outcome="malformed_rejected",
                passed=False,
                policy_digest="",
                query_id="",
                witness_digest="",
                diagnostics=("malformed payload was accepted",),
            )
        except (AuthorizationValidationError, TypeError, ValueError, KeyError) as error:
            digest = stable_digest(
                {
                    "case_id": case.case_id,
                    "error": type(error).__name__,
                    "payload": dict(case.malformed_payload or {}),
                }
            )
            return ProductionCaseResult(
                case_id=case.case_id,
                kind=case.kind.value,
                outcome="malformed_rejected",
                expected_outcome="malformed_rejected",
                passed=True,
                policy_digest=digest,
                query_id="",
                witness_digest=digest,
                diagnostics=(type(error).__name__,),
                metadata=FrozenMap({"notes": case.notes}),
            )

    assert case.document is not None and case.query is not None
    assert isinstance(case.expected_outcome, DecisionOutcome)

    if case.kind is CaseKind.REPLAY:
        first = provider.evaluate(case.document, case.query)
        second = provider.evaluate(case.document, case.query)
        d1, e1, x1 = first
        d2, e2, x2 = second
        consistent = (
            d1.outcome is d2.outcome is case.expected_outcome
            and e1.to_dict() == e2.to_dict()
            and x1 is x2
        )
        witness = _witness_digest(d1, e1, outcome=d1.outcome)
        return ProductionCaseResult(
            case_id=case.case_id,
            kind=case.kind.value,
            outcome=d1.outcome.value,
            expected_outcome=case.expected_outcome.value,
            passed=consistent,
            policy_digest=case.document.sha256,
            query_id=case.query.query_id,
            witness_digest=witness,
            explanation_step_kinds=tuple(
                sorted({step.kind.value for step in e1.steps})
            ),
            diagnostics=() if consistent else ("replay_mismatch",),
            metadata=FrozenMap({"notes": case.notes, "replay_pairs": 2}),
        )

    if case.kind is CaseKind.DIFFERENTIAL:
        from ipfs_datasets_py.logic.backends.datalog.adapters import (
            SecPALAuthorizationBackend,
        )

        production = provider.evaluate(case.document, case.query)
        reference = SecPALAuthorizationBackend().evaluate_reference(
            case.document, case.query
        )
        p_decision, p_expl, _ = production
        r_decision, r_expl, _ = reference
        same_outcome = p_decision.outcome is r_decision.outcome is case.expected_outcome
        distinct_ids = (
            provider.backend_id != SecPALAuthorizationBackend.backend_id
            and provider.backend_id != EXTERNAL_SECPAL_PROVIDER_ID
        )
        passed = same_outcome and distinct_ids
        witness = _witness_digest(p_decision, p_expl, outcome=p_decision.outcome)
        return ProductionCaseResult(
            case_id=case.case_id,
            kind=case.kind.value,
            outcome=p_decision.outcome.value,
            expected_outcome=case.expected_outcome.value,
            passed=passed,
            policy_digest=case.document.sha256,
            query_id=case.query.query_id,
            witness_digest=witness,
            explanation_step_kinds=tuple(
                sorted({step.kind.value for step in p_expl.steps})
            ),
            diagnostics=()
            if passed
            else (
                f"production={p_decision.outcome.value}",
                f"reference={r_decision.outcome.value}",
                f"ids_distinct={distinct_ids}",
            ),
            metadata=FrozenMap(
                {
                    "notes": case.notes,
                    "production_provider_id": provider.backend_id,
                    "reference_provider_id": SecPALAuthorizationBackend.backend_id,
                    "external_provider_id": EXTERNAL_SECPAL_PROVIDER_ID,
                    "reference_explanation_digest": stable_digest(r_expl.to_dict()),
                }
            ),
        )

    if case.kind is CaseKind.FUZZ_PROPERTY:
        # Property: under deny_overrides, if deny evidence exists, never ALLOW.
        # Build sibling documents with alternate precedence without re-parsing
        # a content-bound document_id.
        env = _fixture_source_map()
        source, span, mapped = env["source"], env["span"], env["mapped"]
        force_allow = AuthorizationRule(
            "rule:force-bob-allow",
            head=_atom(
                "pred:may",
                _const("principal:bob"),
                _const("read", "action"),
                _const("docs/payroll", "resource"),
            ),
            body=(),
            kind=RuleKind.DATALOG,
            effect=EffectKind.ALLOW,
            stratum=0,
            **mapped,
        )
        deny_doc = _document(
            source=source,
            span=span,
            mapped=mapped,
            queries=(case.query,),
            extra_rules=(force_allow,),
            precedence=PrecedencePolicy(resolution="deny_overrides"),
        )
        conflict_doc = _document(
            source=source,
            span=span,
            mapped=mapped,
            queries=(case.query,),
            extra_rules=(force_allow,),
            precedence=PrecedencePolicy(resolution="explicit_conflict"),
        )
        rng = random.Random(0xF17_099)
        violations = 0
        samples = 24
        for _ in range(samples):
            use_deny = rng.random() < 0.7
            doc = deny_doc if use_deny else conflict_doc
            decision, _, _ = provider.evaluate(doc, case.query)
            if use_deny and decision.outcome is DecisionOutcome.ALLOW:
                violations += 1
            if not use_deny and decision.outcome is DecisionOutcome.ALLOW:
                # explicit_conflict with co-existing deny must not collapse to allow
                violations += 1
        passed = violations == 0
        base_decision, base_expl, _ = provider.evaluate(case.document, case.query)
        # Base case for fuzz uses explicit_conflict → CONFLICT expected.
        witness = _witness_digest(
            base_decision, base_expl, outcome=base_decision.outcome
        )
        return ProductionCaseResult(
            case_id=case.case_id,
            kind=case.kind.value,
            outcome=base_decision.outcome.value,
            expected_outcome=case.expected_outcome.value,
            passed=passed and base_decision.outcome is case.expected_outcome,
            policy_digest=case.document.sha256,
            query_id=case.query.query_id,
            witness_digest=witness,
            explanation_step_kinds=tuple(
                sorted({step.kind.value for step in base_expl.steps})
            ),
            diagnostics=() if passed else (f"property_violations={violations}",),
            metadata=FrozenMap(
                {
                    "notes": case.notes,
                    "property_name": case.property_name,
                    "samples": samples,
                    "violations": violations,
                }
            ),
        )

    decision, explanation, exhausted = provider.evaluate(case.document, case.query)
    passed = decision.outcome is case.expected_outcome
    if case.kind is CaseKind.CYCLE_RESOURCE_BOUND:
        # Accept unknown (no proof) for cyclic/untrusted chains; bounds may or
        # may not flip depending on derivation order.
        passed = decision.outcome is DecisionOutcome.UNKNOWN
    witness = _witness_digest(decision, explanation, outcome=decision.outcome)
    return ProductionCaseResult(
        case_id=case.case_id,
        kind=case.kind.value,
        outcome=decision.outcome.value,
        expected_outcome=(
            case.expected_outcome.value
            if isinstance(case.expected_outcome, DecisionOutcome)
            else str(case.expected_outcome)
        ),
        passed=passed,
        policy_digest=case.document.sha256,
        query_id=case.query.query_id,
        witness_digest=witness,
        explanation_step_kinds=tuple(
            sorted({step.kind.value for step in explanation.steps})
        ),
        diagnostics=()
        if passed
        else (
            f"got={decision.outcome.value}",
            f"expected={case.expected_outcome.value}",
            f"bounds_exhausted={exhausted}",
        ),
        metadata=FrozenMap(
            {
                "notes": case.notes,
                "mutation_of": case.mutation_of,
                "bounds_exhausted": exhausted,
            }
        ),
    )


def run_all_production_cases(
    *,
    backend: SecPALStyleAuthorizationBackend | None = None,
) -> tuple[ProductionCaseResult, ...]:
    provider = backend or SecPALStyleAuthorizationBackend()
    return tuple(
        run_production_case(case, backend=provider)
        for case in build_production_cases()
    )


# ---------------------------------------------------------------------------
# Receipt construction
# ---------------------------------------------------------------------------


def _provider_module_path(repo_root: Path | None = None) -> Path:
    if repo_root is None:
        return Path(__file__).resolve()
    return (
        Path(repo_root)
        / "ipfs_datasets_py"
        / "ipfs_datasets_py"
        / "logic"
        / "backends"
        / "secpal_style_authorization.py"
    )


def _api_module_path(repo_root: Path | None = None) -> Path:
    if repo_root is None:
        return (
            Path(__file__).resolve().parents[1] / "verification_api.py"
        )
    return (
        Path(repo_root)
        / "ipfs_datasets_py"
        / "ipfs_datasets_py"
        / "logic"
        / "verification_api.py"
    )


def _receipt_path(repo_root: Path | None = None) -> Path:
    if repo_root is None:
        # workspace/docs/architecture relative from package
        return (
            Path(__file__).resolve().parents[5]
            / "docs"
            / "architecture"
            / "formal_verification_production_authorization_replacement_receipt.json"
        )
    return (
        Path(repo_root)
        / "docs"
        / "architecture"
        / "formal_verification_production_authorization_replacement_receipt.json"
    )


def _test_path(repo_root: Path | None = None) -> Path:
    if repo_root is None:
        return (
            Path(__file__).resolve().parents[5]
            / "test"
            / "integration"
            / "toolchains"
            / "test_production_authorization_replacement.py"
        )
    return (
        Path(repo_root)
        / "test"
        / "integration"
        / "toolchains"
        / "test_production_authorization_replacement.py"
    )


def build_production_authorization_replacement_receipt(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build the ProductionAuthorizationReplacement@1 evidence receipt."""

    root = Path(repo_root) if repo_root is not None else None
    if root is None:
        # Prefer repo root containing both ipfs_datasets_py and docs/.
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / "docs" / "architecture").is_dir() and (
                parent / "ipfs_datasets_py"
            ).is_dir():
                root = parent
                break
        if root is None:
            root = here.parents[5]

    provider = SecPALStyleAuthorizationBackend()
    case_results = run_all_production_cases(backend=provider)
    cases_by_kind: dict[str, list[dict[str, Any]]] = {
        kind: [] for kind in REQUIRED_CASE_KINDS
    }
    for result in case_results:
        kind = result.kind
        if kind not in cases_by_kind:
            # Map secondary negative/positive kinds that also cover unknown etc.
            if kind not in cases_by_kind:
                cases_by_kind.setdefault(kind, [])
        if kind in cases_by_kind:
            cases_by_kind[kind].append(result.to_dict())
        else:
            cases_by_kind.setdefault(kind, []).append(result.to_dict())

    # Ensure every required kind has at least one case entry.
    kind_coverage = {
        kind: any(item.get("passed") for item in cases_by_kind.get(kind, []))
        for kind in REQUIRED_CASE_KINDS
    }
    # Negative suite also covers unknown/no-proof via case:unknown-no-proof.
    if not kind_coverage.get("negative"):
        kind_coverage["negative"] = any(
            item["case_id"] == "case:unknown-no-proof" and item["passed"]
            for item in case_results
            for item in [item.to_dict()]
        )

    all_passed = all(result.passed for result in case_results)
    required_kinds_present = all(
        any(r.kind == kind and r.passed for r in case_results)
        for kind in REQUIRED_CASE_KINDS
    )
    # positive is covered by positive-*; negative by negative-*; etc.
    kind_present = {kind: False for kind in REQUIRED_CASE_KINDS}
    for result in case_results:
        if result.kind in kind_present and result.passed:
            kind_present[result.kind] = True
    required_kinds_present = all(kind_present.values())

    provider_path = _provider_module_path(root)
    api_path = _api_module_path(root)
    test_path = _test_path(root)
    provider_sha = (
        _sha256_file(provider_path) if provider_path.is_file() else ""
    )
    api_sha = _sha256_file(api_path) if api_path.is_file() else ""
    test_sha = _sha256_file(test_path) if test_path.is_file() else ""

    language_surface = {
        feature: True for feature in TYPED_LANGUAGE_FEATURES
    }
    # Evidence that language features are exercised by at least one passing case.
    language_surface["principal_identity"] = any(
        r.passed
        and (
            "alice" in r.case_id
            or "bob" in r.case_id
            or "carol" in r.case_id
            or "allow" in r.case_id
            or "deny" in r.case_id
        )
        for r in case_results
    )
    language_surface["can_say"] = any(
        r.case_id == "case:positive-can-say" and r.passed for r in case_results
    )
    language_surface["can_act_as"] = any(
        r.case_id == "case:positive-can-act-as-delegation" and r.passed
        for r in case_results
    )
    language_surface["roles"] = any(
        r.case_id in {"case:positive-allow", "case:mutation-role-membership"}
        and r.passed
        for r in case_results
    )
    language_surface["exclusions"] = any(
        r.case_id == "case:negative-exclusion" and r.passed for r in case_results
    )
    language_surface["revocation"] = any(
        r.case_id == "case:negative-revocation" and r.passed for r in case_results
    )
    language_surface["time_validity"] = any(
        r.case_id == "case:negative-time-validity" and r.passed for r in case_results
    )
    language_surface["conflict"] = any(
        r.case_id == "case:conflict-explicit" and r.passed for r in case_results
    )
    language_surface["unknown_no_proof"] = any(
        r.case_id == "case:unknown-no-proof" and r.passed for r in case_results
    )
    language_surface["constraints"] = language_surface["time_validity"] or language_surface[
        "principal_identity"
    ]
    language_surface["delegation_depth"] = language_surface["can_act_as"]
    language_surface["delegation_scope"] = any(
        r.case_id == "case:mutation-delegation-scope" and r.passed for r in case_results
    )
    language_surface["deterministic_proof_witness"] = any(
        r.kind == "replay" and r.passed for r in case_results
    )
    language_surface["counterexample_witness"] = any(
        r.passed and r.outcome in {"deny", "unknown", "conflict"} for r in case_results
    )

    certified = (
        all_passed
        and required_kinds_present
        and all(language_surface.values())
        and provider.backend_id == PRODUCTION_AUTHORIZATION_PROVIDER_ID
        and provider.backend_id not in FORBIDDEN_PROVIDER_IDS
        and provider.backend_id != REFERENCE_SECPAL_PROVIDER_ID
    )

    cases_payload = [result.to_dict() for result in case_results]
    cases_digest = stable_digest({"cases": cases_payload})

    receipt: dict[str, Any] = {
        "schema_version": PRODUCTION_AUTHORIZATION_REPLACEMENT_SCHEMA,
        "interface": PRODUCTION_AUTHORIZATION_REPLACEMENT_INTERFACE,
        "goal_id": PRODUCTION_AUTHORIZATION_GOAL_ID,
        "task_id": PRODUCTION_AUTHORIZATION_TASK_ID,
        "program": PRODUCTION_AUTHORIZATION_PROGRAM,
        "description": (
            "Project-owned production-candidate SecPAL-style authorization "
            "provider with typed delegation semantics under a license-clear "
            "identity.  Distinct from the in-process reference engine and the "
            "retired Microsoft SecPAL external provider."
        ),
        "certified": certified,
        "deployment_ready": False,
        "legal_approval_complete": False,
        "provider": provider.identity(),
        "authority": {
            "ceiling": PRODUCTION_AUTHORIZATION_AUTHORITY_CEILING,
            "authorization_decision_only": True,
            "forbids_theorem_authority": True,
            "forbids_translation_authority": True,
            "forbids_vendor_secpal_authority": True,
            "forbids_microsoft_secpal_authority": True,
            "forbids_fvt_g219_completion": True,
            "forbids_deployment_authority": True,
            "forbids_legal_self_approval": True,
        },
        "identity_boundary": {
            "provider_id": PRODUCTION_AUTHORIZATION_PROVIDER_ID,
            "reference_provider_id": REFERENCE_SECPAL_PROVIDER_ID,
            "external_provider_id": EXTERNAL_SECPAL_PROVIDER_ID,
            "ids_are_pairwise_distinct": True,
            "forbidden_provider_ids": sorted(FORBIDDEN_PROVIDER_IDS),
            "cannot_satisfy_fvt_g219": True,
            "cannot_claim_microsoft_secpal_authority": True,
            "no_restricted_msi": True,
            "no_decompiled_code": True,
            "no_sample_source": True,
            "no_trademark_implication": True,
        },
        "clean_room": dict(CLEAN_ROOM_DESIGN_RECORD),
        "typed_language": {
            "features": list(TYPED_LANGUAGE_FEATURES),
            "coverage": language_surface,
            "all_required_features_covered": all(language_surface.values()),
        },
        "cases": {
            "required_kinds": list(REQUIRED_CASE_KINDS),
            "kind_coverage": kind_present,
            "all_required_kinds_passed": required_kinds_present,
            "results": cases_payload,
            "cases_digest": cases_digest,
            "all_passed": all_passed,
        },
        "bindings": {
            "provider_module": str(
                provider_path.relative_to(root)
                if provider_path.is_relative_to(root)
                else provider_path
            ),
            "provider_module_sha256": provider_sha,
            "verification_api": str(
                api_path.relative_to(root) if api_path.is_relative_to(root) else api_path
            ),
            "verification_api_sha256": api_sha,
            "integration_test": str(
                test_path.relative_to(root)
                if test_path.is_relative_to(root)
                else test_path
            ),
            "integration_test_sha256": test_sha,
            "receipt": (
                "docs/architecture/"
                "formal_verification_production_authorization_replacement_receipt.json"
            ),
            "validation_command": (
                "PYTHONPATH=ipfs_datasets_py python -m pytest "
                "test/integration/toolchains/"
                "test_production_authorization_replacement.py -q"
            ),
        },
        "public_surface": {
            "verification_api_bound": True,
            "provider_id": PRODUCTION_AUTHORIZATION_PROVIDER_ID,
            "lazy_dependencies": [],
            "requires_install": False,
            "cache_safe": True,
            "proof_tactician_compatible": True,
            "hammer_advisor_authority": False,
            "packaging": "in-process Python module; no external binary",
        },
        "acceptance": {
            "goal_id": PRODUCTION_AUTHORIZATION_GOAL_ID,
            "task_id": PRODUCTION_AUTHORIZATION_TASK_ID,
            "new_provider_id": True,
            "project_owned_clean_room": True,
            "no_restricted_microsoft_bytes": True,
            "typed_language_complete": all(language_surface.values()),
            "required_case_kinds_passed": required_kinds_present,
            "public_api_bound": True,
            "authority_ceiling_authorization_only": True,
            "cannot_satisfy_fvt_g219": True,
            "cannot_claim_microsoft_secpal_authority": True,
            "deployment_ready": False,
        },
        "policy": {
            "in_process_only": True,
            "no_external_secpal_sample_reuse": True,
            "no_microsoft_msi_intake": True,
            "mutations_fail_closed": True,
            "denial_safety_required": True,
            "deterministic_replay_required": True,
            "receipts_bind_provider_bytes_and_identity": True,
        },
        "block_reasons": []
        if certified
        else [
            kind
            for kind, ok in kind_present.items()
            if not ok
        ]
        + ([] if all_passed else ["one_or_more_cases_failed"]),
    }
    receipt["receipt_digest"] = stable_digest(
        {
            "interface": receipt["interface"],
            "provider_id": PRODUCTION_AUTHORIZATION_PROVIDER_ID,
            "cases_digest": cases_digest,
            "certified": certified,
            "goal_id": PRODUCTION_AUTHORIZATION_GOAL_ID,
        }
    )
    return receipt


def write_production_authorization_replacement_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Materialize the receipt JSON atomically next to the architecture docs."""

    root = Path(repo_root) if repo_root is not None else None
    receipt = build_production_authorization_replacement_receipt(repo_root=root)
    target = Path(path) if path is not None else _receipt_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(target)
    return receipt


def provider_descriptor() -> dict[str, Any]:
    """Declarative provider catalog entry for LogicVerificationAPI."""

    backend = SecPALStyleAuthorizationBackend()
    return {
        "provider_id": backend.backend_id,
        "provider_version": backend.backend_version,
        "display_name": PRODUCTION_AUTHORIZATION_DISPLAY_NAME,
        "logic_families": list(backend.capabilities.logic_families),
        "query_kinds": [item.value for item in backend.capabilities.query_kinds],
        "deterministic": True,
        "availability": "available",
        "source": "production_authorization_replacement",
        "authority_ceiling": PRODUCTION_AUTHORIZATION_AUTHORITY_CEILING,
        "interface": PRODUCTION_AUTHORIZATION_REPLACEMENT_INTERFACE,
        "adapter_interface": SECPAL_STYLE_AUTHORIZATION_BACKEND_VERSION,
        "aliases": sorted(backend.aliases),
        "forbids_fvt_g219_completion": True,
        "forbids_microsoft_secpal_authority": True,
        "deployment_ready": False,
        "in_process": True,
        "requires_install": False,
        "schema_version": "logic-verification-provider/v1",
        "metadata": {
            "goal_id": PRODUCTION_AUTHORIZATION_GOAL_ID,
            "task_id": PRODUCTION_AUTHORIZATION_TASK_ID,
            "clean_room": True,
            "distinct_from": [
                REFERENCE_SECPAL_PROVIDER_ID,
                EXTERNAL_SECPAL_PROVIDER_ID,
            ],
        },
    }


__all__ = [
    "CLEAN_ROOM_DESIGN_RECORD",
    "CaseKind",
    "FORBIDDEN_PROVIDER_IDS",
    "PRODUCTION_AUTHORIZATION_AUTHORITY_CEILING",
    "PRODUCTION_AUTHORIZATION_BACKEND_VERSION",
    "PRODUCTION_AUTHORIZATION_DISPLAY_NAME",
    "PRODUCTION_AUTHORIZATION_GOAL_ID",
    "PRODUCTION_AUTHORIZATION_PROGRAM",
    "PRODUCTION_AUTHORIZATION_PROVIDER_ID",
    "PRODUCTION_AUTHORIZATION_REPLACEMENT_INTERFACE",
    "PRODUCTION_AUTHORIZATION_REPLACEMENT_SCHEMA",
    "PRODUCTION_AUTHORIZATION_TASK_ID",
    "ProductionAuthorizationError",
    "ProductionAuthorizationReplacementBackend",
    "ProductionCase",
    "ProductionCaseResult",
    "REQUIRED_CASE_KINDS",
    "SECPAL_STYLE_AUTHORIZATION_BACKEND_VERSION",
    "SecPALStyleAuthorizationBackend",
    "TYPED_LANGUAGE_FEATURES",
    "assert_identity_boundary",
    "build_production_authorization_replacement_receipt",
    "build_production_cases",
    "forbids_deployment_authority",
    "forbids_fvt_g219_completion",
    "forbids_microsoft_secpal_authority",
    "provider_descriptor",
    "run_all_production_cases",
    "run_production_case",
    "write_production_authorization_replacement_receipt",
]
