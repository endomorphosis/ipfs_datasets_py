"""Authorization and policy mutation operators (AAE-018).

Interface: ``AuthorizationPolicyMutationOperators@1``

Sealed, bounded, deterministic operator catalogue for the
``authorization_policy`` operator class. Coverage is normative and complete
for the plan's authorization/policy family:

* authentication bypass
* caller-selected / cross-tenant trust
* missing attenuation
* wrong or omitted audience
* accepted expired delegation
* accepted revoked capability
* missing confirmation and cross-action confirmation replay
* stale policy / fencing and policy default-to-allow
* payment-as-authority

High-risk defaults are mandatory: catalogue operators admit only
``critical_security``, ``authorization``, or ``financial_legal`` risk
classes (default ``critical_security``). Operators never open a store,
mutate production worktrees, or grant assurance authority.

Generation callables that rewrite source live in AAE-022; this module owns
canonical declarations, family coverage, and registry admission for the
class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceBaseError,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.mutation_contracts import (
    MutationOperatorDefinition,
    MutationRiskClass,
    MutationTarget,
    OperatorClass,
    PropertyClass,
    RollbackDeclaration,
    RollbackStrategy,
    SandboxMode,
    SandboxRequirement,
    ScopeLimits,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.base import (
    DeclarationBackedOperator,
    MutationOperator,
    OperatorBaseError,
    OperatorBoundError,
    OperatorDeclarationError,
    OperatorRollbackRecord,
    assert_operator_bounded,
    canonicalize_operator_declaration,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.operators.registry import (
    MutationOperatorRegistry,
    MutationOperatorRegistryBuilder,
    OperatorRegistryError,
    build_mutation_operator_registry,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

AUTHORIZATION_POLICY_OPERATORS_INTERFACE: Final[str] = (
    "AuthorizationPolicyMutationOperators@1"
)
AUTHORIZATION_POLICY_OPERATORS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-"
    "authorization-policy-mutation-operators@1"
)
AUTHORIZATION_POLICY_OPERATORS_VERSION: Final[str] = "1"
AUTHORIZATION_POLICY_OPERATORS_PRODUCER: Final[str] = (
    "adversarial-assurance.authorization-policy-mutation-operators@1"
)
AUTHORIZATION_POLICY_OPERATOR_VERSION: Final[str] = "1"

# Tight default scope for security-sensitive rewrites.
_DEFAULT_MAX_FILES: Final[int] = 1
_DEFAULT_MAX_SYMBOLS: Final[int] = 2
_DEFAULT_MAX_SPAN_LINES: Final[int] = 48
_DEFAULT_MAX_MUTANTS_PER_TARGET: Final[int] = 4

# High-risk defaults: security-class operators must not down-rank to local/low.
HIGH_RISK_CLASSES: Final[frozenset[str]] = frozenset(
    {
        MutationRiskClass.CRITICAL_SECURITY.value,
        MutationRiskClass.AUTHORIZATION.value,
        MutationRiskClass.FINANCIAL_LEGAL.value,
    }
)
DEFAULT_AUTH_RISK_CLASS: Final[str] = MutationRiskClass.CRITICAL_SECURITY.value

_DEFAULT_LANGUAGES: Final[tuple[str, ...]] = ("python", "typescript")
_DEFAULT_ARTIFACT_TYPES: Final[tuple[str, ...]] = (
    "source_module",
    "policy_artifact",
)
_DEFAULT_PREREQUISITES: Final[tuple[str, ...]] = (
    "parsed_ast",
    "symbol_table",
)


class AuthorizationPolicyError(AssuranceBaseError):
    """Raised when an authorization/policy operator contract fails closed."""


class AuthorizationPolicyCoverageError(AuthorizationPolicyError):
    """Raised when the catalogue does not cover a required family."""


class AuthorizationPolicyRiskError(AuthorizationPolicyError):
    """Raised when an operator uses a non-high-risk default."""


class AuthorizationPolicyFamily(str, Enum):
    """Closed family keys required by plan acceptance for AAE-018."""

    AUTHENTICATION = "authentication"
    TENANT = "tenant"
    ATTENUATION = "attenuation"
    AUDIENCE = "audience"
    EXPIRY = "expiry"
    REVOCATION = "revocation"
    CONFIRMATION = "confirmation"
    STALE_DEFAULT_POLICY = "stale_default_policy"
    PAYMENT_AS_AUTHORITY = "payment_as_authority"


REQUIRED_AUTHORIZATION_POLICY_FAMILIES: Final[frozenset[str]] = frozenset(
    item.value for item in AuthorizationPolicyFamily
)


# ---------------------------------------------------------------------------
# Spec / recipe types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorizationPolicyOperatorSpec:
    """Declarative recipe for one sealed authorization/policy operator.

    Specs are pure data used to construct ``MutationOperatorDefinition``
    values under high-risk defaults. They are not durable CAS records.
    """

    operator_id: str
    family: AuthorizationPolicyFamily | str
    semantic_intent: str
    syntactic_transformation: str
    expected_violated_property_classes: Sequence[PropertyClass | str]
    likely_equivalent_conditions: Sequence[str] = ()
    risk_class: MutationRiskClass | str = DEFAULT_AUTH_RISK_CLASS
    max_mutants_per_target: int = _DEFAULT_MAX_MUTANTS_PER_TARGET
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.operator_id) is not str or not self.operator_id.strip():
            raise AuthorizationPolicyError("operator_id must be a nonempty string")
        family = self.family
        if isinstance(family, AuthorizationPolicyFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = AuthorizationPolicyFamily(family).value
            except ValueError as exc:
                raise AuthorizationPolicyError(
                    f"unsupported authorization policy family: {family!r}"
                ) from exc
        else:
            raise AuthorizationPolicyError("family must be AuthorizationPolicyFamily or str")
        object.__setattr__(self, "family", family_value)
        risk = self.risk_class
        if isinstance(risk, MutationRiskClass):
            risk_value = risk.value
        elif type(risk) is str:
            try:
                risk_value = MutationRiskClass(risk).value
            except ValueError as exc:
                raise AuthorizationPolicyError(
                    f"unsupported risk_class: {risk!r}"
                ) from exc
        else:
            raise AuthorizationPolicyError("risk_class must be MutationRiskClass or str")
        if risk_value not in HIGH_RISK_CLASSES:
            raise AuthorizationPolicyRiskError(
                f"authorization/policy operators require high-risk defaults; "
                f"got risk_class={risk_value!r}, allowed={sorted(HIGH_RISK_CLASSES)}"
            )
        object.__setattr__(self, "risk_class", risk_value)
        if type(self.semantic_intent) is not str or not self.semantic_intent.strip():
            raise AuthorizationPolicyError("semantic_intent must be nonempty")
        if (
            type(self.syntactic_transformation) is not str
            or not self.syntactic_transformation.strip()
        ):
            raise AuthorizationPolicyError(
                "syntactic_transformation must be nonempty"
            )
        props = tuple(self.expected_violated_property_classes)
        if not props:
            raise AuthorizationPolicyError(
                "expected_violated_property_classes must not be empty"
            )
        object.__setattr__(self, "expected_violated_property_classes", props)
        object.__setattr__(
            self,
            "likely_equivalent_conditions",
            tuple(self.likely_equivalent_conditions or ()),
        )
        if (
            type(self.max_mutants_per_target) is not int
            or isinstance(self.max_mutants_per_target, bool)
            or self.max_mutants_per_target < 1
        ):
            raise AuthorizationPolicyError(
                "max_mutants_per_target must be a positive integer"
            )
        meta = dict(self.metadata or {})
        # Key must not contain private-field markers such as "authorization".
        meta.setdefault("policy_family", family_value)
        try:
            reject_private_model_authority_and_host_fallbacks(
                meta, path="AuthorizationPolicyOperatorSpec.metadata"
            )
            cid_for_structured(meta)
        except Exception as exc:  # noqa: BLE001
            raise AuthorizationPolicyError(
                "metadata must be DAG-JSON structured data without model authority"
            ) from exc
        object.__setattr__(self, "metadata", MappingProxyType(meta))


def _default_scope() -> ScopeLimits:
    return ScopeLimits(
        max_files=_DEFAULT_MAX_FILES,
        max_symbols=_DEFAULT_MAX_SYMBOLS,
        max_span_lines=_DEFAULT_MAX_SPAN_LINES,
        allow_cross_module=False,
        allow_verifier_mutation=False,
    )


def _default_rollback() -> RollbackDeclaration:
    return RollbackDeclaration(
        strategy=RollbackStrategy.WORKTREE_DISCARD,
        requires_clean_worktree=True,
        preserves_production=True,
    )


def _default_sandbox() -> SandboxRequirement:
    return SandboxRequirement(
        mode=SandboxMode.DISPOSABLE_WORKTREE,
        network_disabled=True,
        production_credentials_forbidden=True,
        disposable_worktree_required=True,
    )


def assert_high_risk_authorization_defaults(
    operator: MutationOperatorDefinition,
) -> None:
    """Fail closed when an authorization/policy operator is not high-risk."""

    if not isinstance(operator, MutationOperatorDefinition):
        raise AuthorizationPolicyError(
            "operator must be a sealed MutationOperatorDefinition"
        )
    if operator.operator_class != OperatorClass.AUTHORIZATION_POLICY.value:
        raise AuthorizationPolicyError(
            "operator_class must be authorization_policy for high-risk auth defaults"
        )
    if operator.risk_class not in HIGH_RISK_CLASSES:
        raise AuthorizationPolicyRiskError(
            f"authorization/policy operator {operator.operator_id} must use a "
            f"high-risk class; got {operator.risk_class!r}"
        )
    props = set(operator.expected_violated_property_classes)
    if PropertyClass.AUTHORIZATION.value not in props and (
        PropertyClass.POLICY_CONSTRAINT.value not in props
    ):
        raise AuthorizationPolicyError(
            f"operator {operator.operator_id} must expect authorization or "
            "policy_constraint property violations"
        )


def build_authorization_policy_operator(
    spec: AuthorizationPolicyOperatorSpec,
    *,
    supported_languages: Sequence[str] | None = None,
    supported_artifact_types: Sequence[str] | None = None,
    target_prerequisites: Sequence[str] | None = None,
    scope_limits: ScopeLimits | None = None,
    rollback: RollbackDeclaration | None = None,
    required_sandbox: SandboxRequirement | None = None,
    operator_version: str = AUTHORIZATION_POLICY_OPERATOR_VERSION,
) -> MutationOperatorDefinition:
    """Seal one authorization/policy operator under high-risk defaults."""

    if not isinstance(spec, AuthorizationPolicyOperatorSpec):
        raise AuthorizationPolicyError(
            "spec must be an AuthorizationPolicyOperatorSpec"
        )
    definition = MutationOperatorDefinition(
        operator_id=spec.operator_id,
        operator_version=operator_version,
        operator_class=OperatorClass.AUTHORIZATION_POLICY,
        supported_languages=tuple(supported_languages or _DEFAULT_LANGUAGES),
        supported_artifact_types=tuple(
            supported_artifact_types or _DEFAULT_ARTIFACT_TYPES
        ),
        target_prerequisites=tuple(
            target_prerequisites or _DEFAULT_PREREQUISITES
        ),
        semantic_intent=spec.semantic_intent,
        expected_violated_property_classes=spec.expected_violated_property_classes,
        risk_class=spec.risk_class,
        likely_equivalent_conditions=spec.likely_equivalent_conditions,
        syntactic_transformation=spec.syntactic_transformation,
        scope_limits=scope_limits or _default_scope(),
        rollback=rollback or _default_rollback(),
        required_sandbox=required_sandbox or _default_sandbox(),
        max_mutants_per_target=spec.max_mutants_per_target,
        deterministic=True,
        notes=spec.notes,
        metadata=dict(spec.metadata),
    )
    try:
        sealed = canonicalize_operator_declaration(definition)
    except (OperatorDeclarationError, OperatorBoundError, OperatorBaseError) as exc:
        raise AuthorizationPolicyError(str(exc)) from exc
    assert_high_risk_authorization_defaults(sealed)
    return sealed


# ---------------------------------------------------------------------------
# Normative catalogue recipes (plan + security campaign)
# ---------------------------------------------------------------------------


def authorization_policy_operator_specs() -> tuple[AuthorizationPolicyOperatorSpec, ...]:
    """Return the closed, ordered set of normative operator recipes."""

    auth = PropertyClass.AUTHORIZATION
    policy = PropertyClass.POLICY_CONSTRAINT
    receipt = PropertyClass.RECEIPT_AUTHENTICITY

    return (
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_bypass_authentication",
            family=AuthorizationPolicyFamily.AUTHENTICATION,
            semantic_intent=(
                "Bypass authentication so unauthenticated callers proceed as "
                "authenticated subjects"
            ),
            syntactic_transformation="replace_authentication_predicate_with_true",
            expected_violated_property_classes=(auth,),
            likely_equivalent_conditions=(
                "authentication_already_optional",
                "endpoint_is_public_by_policy",
            ),
            risk_class=MutationRiskClass.CRITICAL_SECURITY,
            notes="Security campaign: authentication bypass",
        ),
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_caller_selected_tenant",
            family=AuthorizationPolicyFamily.TENANT,
            semantic_intent=(
                "Trust a caller-supplied tenant identifier without binding it "
                "to authenticated subject membership"
            ),
            syntactic_transformation="prefer_request_tenant_claim_over_bound_tenant",
            expected_violated_property_classes=(auth, policy),
            likely_equivalent_conditions=(
                "single_tenant_deployment",
                "tenant_header_already_ignored",
            ),
            risk_class=MutationRiskClass.CRITICAL_SECURITY,
            notes="Security campaign: caller-selected tenant",
        ),
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_missing_attenuation",
            family=AuthorizationPolicyFamily.ATTENUATION,
            semantic_intent=(
                "Drop capability attenuation so a delegated token retains "
                "broader rights than the proof chain authorizes"
            ),
            syntactic_transformation="omit_capability_attenuation_intersection",
            expected_violated_property_classes=(auth, policy),
            likely_equivalent_conditions=(
                "delegation_has_no_narrowing_clauses",
                "attenuation_set_already_empty",
            ),
            risk_class=MutationRiskClass.CRITICAL_SECURITY,
            notes="Security campaign: missing attenuation",
        ),
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_wrong_audience",
            family=AuthorizationPolicyFamily.AUDIENCE,
            semantic_intent=(
                "Accept a token or authorization whose audience does not match "
                "the defending service or action"
            ),
            syntactic_transformation="skip_or_widen_audience_check",
            expected_violated_property_classes=(auth, receipt),
            likely_equivalent_conditions=(
                "audience_claim_absent_and_optional",
                "single_audience_deployment",
            ),
            risk_class=MutationRiskClass.CRITICAL_SECURITY,
            notes="Wrong or omitted audience binding",
        ),
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_accept_expired_delegation",
            family=AuthorizationPolicyFamily.EXPIRY,
            semantic_intent=(
                "Accept expired tokens or delegations by omitting or weakening "
                "not-before/expiry enforcement"
            ),
            syntactic_transformation="disable_token_expiry_check",
            expected_violated_property_classes=(auth,),
            likely_equivalent_conditions=(
                "token_has_no_expiry_claim",
                "clock_skew_window_already_unbounded",
            ),
            risk_class=MutationRiskClass.CRITICAL_SECURITY,
            notes="Security campaign: accepted expired delegations",
        ),
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_accept_revoked_capability",
            family=AuthorizationPolicyFamily.REVOCATION,
            semantic_intent=(
                "Accept revoked capabilities by skipping revocation-list or "
                "revocation-proof consultation"
            ),
            syntactic_transformation="skip_revocation_status_lookup",
            expected_violated_property_classes=(auth, policy),
            likely_equivalent_conditions=(
                "revocation_set_empty_and_fresh",
                "capability_never_revocable",
            ),
            risk_class=MutationRiskClass.CRITICAL_SECURITY,
            notes="Security campaign: accepted revoked delegations",
        ),
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_missing_confirmation",
            family=AuthorizationPolicyFamily.CONFIRMATION,
            semantic_intent=(
                "Proceed with a high-risk action without a required human or "
                "out-of-band confirmation receipt"
            ),
            syntactic_transformation="omit_required_confirmation_gate",
            expected_violated_property_classes=(auth, policy),
            likely_equivalent_conditions=(
                "confirmation_not_required_for_action",
                "confirmation_already_satisfied_in_scope",
            ),
            risk_class=MutationRiskClass.CRITICAL_SECURITY,
            notes="Security campaign: missing confirmation",
        ),
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_cross_action_confirmation_replay",
            family=AuthorizationPolicyFamily.CONFIRMATION,
            semantic_intent=(
                "Replay a confirmation receipt across a different action, "
                "target, or resource binding"
            ),
            syntactic_transformation="reuse_confirmation_without_action_binding",
            expected_violated_property_classes=(auth, receipt),
            likely_equivalent_conditions=(
                "confirmation_is_unscoped_by_design",
                "actions_share_identical_confirmation_scope",
            ),
            risk_class=MutationRiskClass.CRITICAL_SECURITY,
            notes="Security campaign: cross-action confirmation replay",
        ),
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_stale_policy_or_fencing_token",
            family=AuthorizationPolicyFamily.STALE_DEFAULT_POLICY,
            semantic_intent=(
                "Authorize using a stale policy revision or fencing token that "
                "no longer matches the current CAS head"
            ),
            syntactic_transformation="accept_stale_policy_revision_or_fence",
            expected_violated_property_classes=(policy, auth),
            likely_equivalent_conditions=(
                "policy_revision_unchanged",
                "fence_token_still_current",
            ),
            risk_class=MutationRiskClass.AUTHORIZATION,
            notes="Security campaign: stale fencing token / stale policy",
        ),
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_policy_default_to_allow",
            family=AuthorizationPolicyFamily.STALE_DEFAULT_POLICY,
            semantic_intent=(
                "When policy lookup fails or is missing, default the decision "
                "to allow instead of fail-closed deny"
            ),
            syntactic_transformation="replace_missing_policy_deny_with_allow",
            expected_violated_property_classes=(policy, auth),
            likely_equivalent_conditions=(
                "policy_always_present",
                "default_allow_is_explicit_policy",
            ),
            risk_class=MutationRiskClass.CRITICAL_SECURITY,
            notes="Security campaign: missing policy default-to-allow",
        ),
        AuthorizationPolicyOperatorSpec(
            operator_id="auth_payment_as_authority",
            family=AuthorizationPolicyFamily.PAYMENT_AS_AUTHORITY,
            semantic_intent=(
                "Treat a payment, invoice, or settlement receipt as sufficient "
                "authorization without an independent capability grant"
            ),
            syntactic_transformation="substitute_payment_receipt_for_authorization",
            expected_violated_property_classes=(
                auth,
                PropertyClass.RECEIPT_AUTHENTICITY,
            ),
            likely_equivalent_conditions=(
                "payment_already_binds_capability_grant",
                "action_requires_no_authorization_beyond_settlement",
            ),
            risk_class=MutationRiskClass.FINANCIAL_LEGAL,
            notes="Security campaign: payment-as-authority",
        ),
    )


# ---------------------------------------------------------------------------
# Operator handles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorizationPolicyOperator(MutationOperator):
    """Declaration-backed authorization/policy operator with family binding.

    Interface membership: ``AuthorizationPolicyMutationOperators@1`` catalogue
    entry. Does not generate source rewrites; generation is owned by AAE-022.
    """

    _definition: MutationOperatorDefinition
    family: str
    spec_operator_id: str

    def __post_init__(self) -> None:
        sealed = canonicalize_operator_declaration(self._definition)
        assert_high_risk_authorization_defaults(sealed)
        if sealed.operator_class != OperatorClass.AUTHORIZATION_POLICY.value:
            raise AuthorizationPolicyError(
                "AuthorizationPolicyOperator requires operator_class "
                "authorization_policy"
            )
        try:
            family_value = AuthorizationPolicyFamily(self.family).value
        except ValueError as exc:
            raise AuthorizationPolicyError(
                f"unsupported authorization policy family: {self.family!r}"
            ) from exc
        meta_family = sealed.metadata.get("policy_family")
        if meta_family is not None and meta_family != family_value:
            raise AuthorizationPolicyError(
                "definition metadata policy_family does not match family binding "
                f"({meta_family!r} != {family_value!r})"
            )
        object.__setattr__(self, "_definition", sealed)
        object.__setattr__(self, "family", family_value)
        if type(self.spec_operator_id) is not str or not self.spec_operator_id:
            raise AuthorizationPolicyError("spec_operator_id must be nonempty")
        if self.spec_operator_id != sealed.operator_id:
            raise AuthorizationPolicyError(
                "spec_operator_id must match definition.operator_id"
            )

    @property
    def definition(self) -> MutationOperatorDefinition:
        return self._definition

    def as_declaration_backed(self) -> DeclarationBackedOperator:
        return DeclarationBackedOperator(_definition=self._definition)

    def supports_target(self, target: MutationTarget) -> bool:
        return self._definition.supports_target(target)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_structured(item) for item in value]
    return value


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise AuthorizationPolicyError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise AuthorizationPolicyError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    return dict(data)


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise AuthorizationPolicyError(f"{name} must be a nonempty trimmed string")
    return value


@dataclass(frozen=True, slots=True)
class AuthorizationPolicyMutationOperators:
    """Immutable catalogue of sealed authorization/policy mutation operators.

    Interface: ``AuthorizationPolicyMutationOperators@1``
    """

    operators: Sequence[AuthorizationPolicyOperator]
    producer_id: str = AUTHORIZATION_POLICY_OPERATORS_PRODUCER
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    catalogue_id: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "catalogue_version",
            "operators",
            "producer_id",
            "notes",
            "metadata",
            "catalogue_id",
            "operator_cids",
            "operator_count",
            "families",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.operators, Sequence) or isinstance(
            self.operators, (str, bytes)
        ):
            raise AuthorizationPolicyError(
                "operators must be a sequence of AuthorizationPolicyOperator"
            )
        sealed: list[AuthorizationPolicyOperator] = []
        seen_ids: set[str] = set()
        seen_cids: set[str] = set()
        families: set[str] = set()
        for item in self.operators:
            if not isinstance(item, AuthorizationPolicyOperator):
                raise AuthorizationPolicyError(
                    "operators entries must be AuthorizationPolicyOperator"
                )
            definition = item.definition
            assert_high_risk_authorization_defaults(definition)
            try:
                assert_operator_bounded(definition)
            except OperatorBoundError as exc:
                raise AuthorizationPolicyError(str(exc)) from exc
            if definition.operator_id in seen_ids:
                raise AuthorizationPolicyError(
                    f"duplicate operator_id in catalogue: {definition.operator_id}"
                )
            if definition.operator_cid in seen_cids:
                raise AuthorizationPolicyError(
                    f"duplicate operator_cid in catalogue: {definition.operator_cid}"
                )
            seen_ids.add(definition.operator_id)
            seen_cids.add(definition.operator_cid)
            families.add(item.family)
            sealed.append(item)

        missing = REQUIRED_AUTHORIZATION_POLICY_FAMILIES - families
        if missing:
            raise AuthorizationPolicyCoverageError(
                "authorization/policy catalogue missing required families: "
                + ", ".join(sorted(missing))
            )

        ordered = tuple(
            sorted(
                sealed,
                key=lambda op: (
                    op.definition.operator_id,
                    op.definition.operator_version,
                    op.definition.operator_cid,
                ),
            )
        )
        object.__setattr__(self, "operators", ordered)
        object.__setattr__(self, "producer_id", _text(self.producer_id, "producer_id"))
        if self.notes is not None:
            object.__setattr__(self, "notes", _text(self.notes, "notes"))
        meta_payload = _thaw_structured(dict(self.metadata or {}))
        try:
            reject_private_model_authority_and_host_fallbacks(
                meta_payload, path="AuthorizationPolicyMutationOperators.metadata"
            )
            cid_for_structured(meta_payload)
        except Exception as exc:  # noqa: BLE001
            raise AuthorizationPolicyError(
                "metadata must be DAG-JSON structured data without model authority"
            ) from exc
        object.__setattr__(self, "metadata", MappingProxyType(meta_payload))

        computed = cid_for_structured(self._identity_payload_without_catalogue_id())
        if self.catalogue_id is None:
            object.__setattr__(self, "catalogue_id", computed)
        else:
            claimed = _text(self.catalogue_id, "catalogue_id")
            if claimed != computed:
                raise AuthorizationPolicyError(
                    "catalogue_id identity mismatch with recomputed catalogue identity"
                )
            object.__setattr__(self, "catalogue_id", claimed)

    def _identity_payload_without_catalogue_id(self) -> dict[str, Any]:
        return {
            "schema": AUTHORIZATION_POLICY_OPERATORS_SCHEMA,
            "interface_id": AUTHORIZATION_POLICY_OPERATORS_INTERFACE,
            "catalogue_version": AUTHORIZATION_POLICY_OPERATORS_VERSION,
            "operators": [
                {
                    "family": item.family,
                    "definition": item.definition.identity_payload(),
                }
                for item in self.operators
            ],
            "producer_id": self.producer_id,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "operator_cids": [item.definition.operator_cid for item in self.operators],
            "operator_count": len(self.operators),
            "families": sorted({item.family for item in self.operators}),
        }

    def identity_payload(self) -> dict[str, Any]:
        payload = self._identity_payload_without_catalogue_id()
        payload["catalogue_id"] = self.catalogue_id
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": AUTHORIZATION_POLICY_OPERATORS_SCHEMA,
            "interface_id": AUTHORIZATION_POLICY_OPERATORS_INTERFACE,
            "catalogue_version": AUTHORIZATION_POLICY_OPERATORS_VERSION,
            "operators": [
                {
                    "family": item.family,
                    "spec_operator_id": item.spec_operator_id,
                    "definition": item.definition.to_dict(),
                }
                for item in self.operators
            ],
            "producer_id": self.producer_id,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "operator_cids": [item.operator_cid for item in self.operators],
            "operator_count": len(self.operators),
            "families": sorted({item.family for item in self.operators}),
            "catalogue_id": self.catalogue_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AuthorizationPolicyMutationOperators":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != AUTHORIZATION_POLICY_OPERATORS_SCHEMA:
            raise AuthorizationPolicyError(
                "unsupported AuthorizationPolicyMutationOperators schema version"
            )
        if payload.pop("interface_id") != AUTHORIZATION_POLICY_OPERATORS_INTERFACE:
            raise AuthorizationPolicyError(
                "unsupported AuthorizationPolicyMutationOperators interface_id"
            )
        version = payload.pop(
            "catalogue_version", AUTHORIZATION_POLICY_OPERATORS_VERSION
        )
        if version != AUTHORIZATION_POLICY_OPERATORS_VERSION:
            raise AuthorizationPolicyError(
                "unsupported AuthorizationPolicyMutationOperators catalogue_version"
            )
        payload.pop("operator_cids", None)
        payload.pop("operator_count", None)
        payload.pop("families", None)
        raw_ops = payload["operators"]
        if not isinstance(raw_ops, list):
            raise AuthorizationPolicyError("operators must be a list")
        operators: list[AuthorizationPolicyOperator] = []
        for entry in raw_ops:
            if not isinstance(entry, Mapping):
                raise AuthorizationPolicyError(
                    "operators entries must be mappings with family and definition"
                )
            definition_raw = entry.get("definition")
            if isinstance(definition_raw, MutationOperatorDefinition):
                definition = definition_raw
            elif isinstance(definition_raw, Mapping):
                definition = MutationOperatorDefinition.from_dict(definition_raw)
            else:
                raise AuthorizationPolicyError(
                    "operators[].definition must be MutationOperatorDefinition or mapping"
                )
            family = entry.get("family")
            if family is None:
                family = definition.metadata.get("policy_family")
            spec_id = entry.get("spec_operator_id", definition.operator_id)
            operators.append(
                AuthorizationPolicyOperator(
                    _definition=definition,
                    family=family,
                    spec_operator_id=spec_id,
                )
            )
        return cls(
            operators=operators,
            producer_id=payload.get(
                "producer_id", AUTHORIZATION_POLICY_OPERATORS_PRODUCER
            ),
            notes=payload.get("notes"),
            metadata=payload.get("metadata") or {},
            catalogue_id=payload.get("catalogue_id"),
        )

    # -- views ---------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.operators)

    def __iter__(self):
        return iter(self.operators)

    def __contains__(self, item: object) -> bool:
        if isinstance(item, AuthorizationPolicyOperator):
            return item.operator_cid in self.operator_cids()
        if isinstance(item, MutationOperatorDefinition):
            return item.operator_cid in self.operator_cids()
        if type(item) is str:
            return item in self.operator_cids() or any(
                op.operator_id == item for op in self.operators
            )
        return False

    def operator_cids(self) -> tuple[str, ...]:
        return tuple(item.operator_cid for item in self.operators)

    def operator_ids(self) -> tuple[str, ...]:
        return tuple(item.operator_id for item in self.operators)

    def families(self) -> tuple[str, ...]:
        return tuple(sorted({item.family for item in self.operators}))

    def definitions(self) -> tuple[MutationOperatorDefinition, ...]:
        return tuple(item.definition for item in self.operators)

    def list_operators(self) -> tuple[AuthorizationPolicyOperator, ...]:
        return tuple(self.operators)

    def operators_for_family(
        self, family: AuthorizationPolicyFamily | str
    ) -> tuple[AuthorizationPolicyOperator, ...]:
        if isinstance(family, AuthorizationPolicyFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = AuthorizationPolicyFamily(family).value
            except ValueError as exc:
                raise AuthorizationPolicyError(
                    f"unsupported authorization policy family: {family!r}"
                ) from exc
        else:
            raise AuthorizationPolicyError(
                "family must be AuthorizationPolicyFamily or str"
            )
        return tuple(item for item in self.operators if item.family == family_value)

    def get(
        self,
        operator_id: str,
        operator_version: str | None = None,
    ) -> AuthorizationPolicyOperator:
        operator_id = _text(operator_id, "operator_id")
        matches = [
            item for item in self.operators if item.operator_id == operator_id
        ]
        if not matches:
            raise AuthorizationPolicyError(f"unknown operator_id: {operator_id}")
        if operator_version is None:
            if len(matches) != 1:
                versions = ", ".join(sorted({item.operator_version for item in matches}))
                raise AuthorizationPolicyError(
                    f"operator_id {operator_id} is ambiguous across versions "
                    f"({versions}); provide operator_version"
                )
            return matches[0]
        operator_version = _text(operator_version, "operator_version")
        for item in matches:
            if item.operator_version == operator_version:
                return item
        raise AuthorizationPolicyError(
            f"unknown operator: {operator_id}@{operator_version}"
        )

    def get_by_cid(self, operator_cid: str) -> AuthorizationPolicyOperator:
        operator_cid = _text(operator_cid, "operator_cid")
        for item in self.operators:
            if item.operator_cid == operator_cid:
                return item
        raise AuthorizationPolicyError(f"unknown operator_cid: {operator_cid}")

    def operators_for_target(
        self, target: MutationTarget
    ) -> tuple[AuthorizationPolicyOperator, ...]:
        if not isinstance(target, MutationTarget):
            raise AuthorizationPolicyError("target must be a MutationTarget")
        return tuple(item for item in self.operators if item.supports_target(target))

    def as_registry(
        self,
        *,
        producer_id: str | None = None,
        notes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MutationOperatorRegistry:
        """Project the catalogue into a ``MutationOperatorRegistry@1``."""

        try:
            return build_mutation_operator_registry(
                self.definitions(),
                producer_id=producer_id
                or AUTHORIZATION_POLICY_OPERATORS_PRODUCER,
                notes=notes if notes is not None else self.notes,
                metadata=metadata if metadata is not None else dict(self.metadata),
            )
        except OperatorRegistryError as exc:
            raise AuthorizationPolicyError(str(exc)) from exc

    def register_into(
        self, builder: MutationOperatorRegistryBuilder
    ) -> tuple[MutationOperatorDefinition, ...]:
        """Admit every catalogue operator into a mutable registry builder."""

        if not isinstance(builder, MutationOperatorRegistryBuilder):
            raise AuthorizationPolicyError(
                "builder must be a MutationOperatorRegistryBuilder"
            )
        sealed: list[MutationOperatorDefinition] = []
        for item in self.operators:
            try:
                sealed.append(builder.register(item.definition))
            except OperatorRegistryError as exc:
                raise AuthorizationPolicyError(str(exc)) from exc
        return tuple(sealed)

    def rollback_record(
        self,
        operator_id: str,
        *,
        pre_mutation_state_cid: str,
        operator_version: str | None = None,
        target: MutationTarget | None = None,
        source_root_cid: str | None = None,
        scope_paths: Sequence[str] = (),
        scope_symbol_ids: Sequence[str] = (),
        notes: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> OperatorRollbackRecord:
        operator = self.get(operator_id, operator_version)
        if target is not None:
            operator.assert_supports_target(target)
        return operator.build_rollback_record(
            pre_mutation_state_cid=pre_mutation_state_cid,
            target=target,
            source_root_cid=source_root_cid,
            scope_paths=scope_paths,
            scope_symbol_ids=scope_symbol_ids,
            notes=notes,
            metadata=metadata,
        )

    def assert_complete_coverage(self) -> None:
        """Re-check that every required family is present (fail-closed)."""

        present = set(self.families())
        missing = REQUIRED_AUTHORIZATION_POLICY_FAMILIES - present
        if missing:
            raise AuthorizationPolicyCoverageError(
                "authorization/policy catalogue missing required families: "
                + ", ".join(sorted(missing))
            )


def build_authorization_policy_operators(
    specs: Iterable[AuthorizationPolicyOperatorSpec] | None = None,
    *,
    producer_id: str = AUTHORIZATION_POLICY_OPERATORS_PRODUCER,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AuthorizationPolicyMutationOperators:
    """Build a sealed catalogue from specs (defaults: normative full set).

    The sealed ``AuthorizationPolicyMutationOperators@1`` interface always
    requires complete family coverage; incomplete assemblies fail closed.
    """

    recipe_list = (
        list(authorization_policy_operator_specs())
        if specs is None
        else list(specs)
    )
    if not recipe_list:
        raise AuthorizationPolicyError(
            "authorization/policy catalogue requires at least one operator spec"
        )
    handles: list[AuthorizationPolicyOperator] = []
    for spec in recipe_list:
        if not isinstance(spec, AuthorizationPolicyOperatorSpec):
            raise AuthorizationPolicyError(
                "specs entries must be AuthorizationPolicyOperatorSpec"
            )
        definition = build_authorization_policy_operator(spec)
        handles.append(
            AuthorizationPolicyOperator(
                _definition=definition,
                family=spec.family,
                spec_operator_id=spec.operator_id,
            )
        )
    catalogue = AuthorizationPolicyMutationOperators(
        operators=handles,
        producer_id=producer_id,
        notes=notes
        if notes is not None
        else (
            "Normative authorization/policy mutation operators with high-risk "
            "defaults (AAE-018)"
        ),
        metadata=metadata or {"task_id": "AAE-018"},
    )
    catalogue.assert_complete_coverage()
    return catalogue


def default_authorization_policy_operators() -> AuthorizationPolicyMutationOperators:
    """Return the normative sealed catalogue (stable identity across calls)."""

    return build_authorization_policy_operators()


def authorization_policy_operator_definitions() -> tuple[MutationOperatorDefinition, ...]:
    """Convenience: sealed definitions only, deterministic order."""

    return default_authorization_policy_operators().definitions()


def authorization_policy_families_covered() -> frozenset[str]:
    """Return the family set covered by the normative catalogue."""

    return frozenset(default_authorization_policy_operators().families())


__all__ = [
    "AUTHORIZATION_POLICY_OPERATORS_INTERFACE",
    "AUTHORIZATION_POLICY_OPERATORS_PRODUCER",
    "AUTHORIZATION_POLICY_OPERATORS_SCHEMA",
    "AUTHORIZATION_POLICY_OPERATORS_VERSION",
    "AUTHORIZATION_POLICY_OPERATOR_VERSION",
    "AuthorizationPolicyCoverageError",
    "AuthorizationPolicyError",
    "AuthorizationPolicyFamily",
    "AuthorizationPolicyMutationOperators",
    "AuthorizationPolicyOperator",
    "AuthorizationPolicyOperatorSpec",
    "AuthorizationPolicyRiskError",
    "DEFAULT_AUTH_RISK_CLASS",
    "HIGH_RISK_CLASSES",
    "REQUIRED_AUTHORIZATION_POLICY_FAMILIES",
    "assert_high_risk_authorization_defaults",
    "authorization_policy_families_covered",
    "authorization_policy_operator_definitions",
    "authorization_policy_operator_specs",
    "build_authorization_policy_operator",
    "build_authorization_policy_operators",
    "default_authorization_policy_operators",
]
