"""Side-effect, error, and retry mutation operators (AAE-017).

Interface: ``SideEffectErrorRetryMutationOperators@1``

Sealed, bounded, deterministic operator catalogue covering both the
``side_effect`` and ``error_retry`` operator classes. Coverage is normative
and complete for the plan's side-effect and error/retry families:

Side-effect families
    omitted, wrong, early, double, and reordered effects; audit omission;
    success-before-observation; missing compensation

Error / retry families
    swallowed or misclassified failures; unavailable/unknown to success/allow;
    missing retry budget; cancellation; integrity bypass/failure

Every operator carries a nonempty semantic intent and equivalence hints
(``likely_equivalent_conditions``). Operators never open a store, mutate
production worktrees, or grant assurance authority.

Generation callables that rewrite source live in AAE-022; this module owns
canonical declarations, family coverage, and registry admission for both
classes.
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

EFFECTS_ERRORS_OPERATORS_INTERFACE: Final[str] = (
    "SideEffectErrorRetryMutationOperators@1"
)
EFFECTS_ERRORS_OPERATORS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-"
    "side-effect-error-retry-mutation-operators@1"
)
EFFECTS_ERRORS_OPERATORS_VERSION: Final[str] = "1"
EFFECTS_ERRORS_OPERATORS_PRODUCER: Final[str] = (
    "adversarial-assurance.side-effect-error-retry-mutation-operators@1"
)
EFFECTS_ERRORS_OPERATOR_VERSION: Final[str] = "1"

_DEFAULT_MAX_FILES: Final[int] = 1
_DEFAULT_MAX_SYMBOLS: Final[int] = 2
_DEFAULT_MAX_SPAN_LINES: Final[int] = 64
_DEFAULT_MAX_MUTANTS_PER_TARGET: Final[int] = 6

DEFAULT_SIDE_EFFECT_RISK_CLASS: Final[str] = MutationRiskClass.HIGH.value
DEFAULT_ERROR_RETRY_RISK_CLASS: Final[str] = MutationRiskClass.CRITICAL_INVARIANT.value

_DEFAULT_LANGUAGES: Final[tuple[str, ...]] = ("python", "typescript")
_DEFAULT_ARTIFACT_TYPES: Final[tuple[str, ...]] = ("source_module",)
_DEFAULT_PREREQUISITES: Final[tuple[str, ...]] = (
    "parsed_ast",
    "symbol_table",
)

# Metadata keys for family / class binding (avoid private-field markers).
_FAMILY_METADATA_KEY: Final[str] = "ee_family"
_OPERATOR_CLASS_METADATA_KEY: Final[str] = "ee_operator_class"

ADMITTED_OPERATOR_CLASSES: Final[frozenset[str]] = frozenset(
    {
        OperatorClass.SIDE_EFFECT.value,
        OperatorClass.ERROR_RETRY.value,
    }
)


class EffectsErrorsError(AssuranceBaseError):
    """Raised when a side-effect/error/retry operator contract fails closed."""


class EffectsErrorsCoverageError(EffectsErrorsError):
    """Raised when the catalogue does not cover a required family or class."""


class EffectsErrorsFamily(str, Enum):
    """Closed family keys required by plan acceptance for AAE-017."""

    # Side effect
    OMITTED_EFFECT = "omitted_effect"
    WRONG_EFFECT = "wrong_effect"
    EARLY_EFFECT = "early_effect"
    DOUBLE_EFFECT = "double_effect"
    REORDERED_EFFECT = "reordered_effect"
    AUDIT_OMISSION = "audit_omission"
    SUCCESS_BEFORE_OBSERVATION = "success_before_observation"
    MISSING_COMPENSATION = "missing_compensation"
    # Error / retry
    SWALLOWED_FAILURE = "swallowed_failure"
    MISCLASSIFIED_FAILURE = "misclassified_failure"
    UNAVAILABLE_TO_SUCCESS = "unavailable_to_success"
    RETRY_BUDGET = "retry_budget"
    CANCELLATION = "cancellation"
    INTEGRITY_FAILURE = "integrity_failure"


REQUIRED_EFFECTS_ERRORS_FAMILIES: Final[frozenset[str]] = frozenset(
    item.value for item in EffectsErrorsFamily
)

REQUIRED_SIDE_EFFECT_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        EffectsErrorsFamily.OMITTED_EFFECT.value,
        EffectsErrorsFamily.WRONG_EFFECT.value,
        EffectsErrorsFamily.EARLY_EFFECT.value,
        EffectsErrorsFamily.DOUBLE_EFFECT.value,
        EffectsErrorsFamily.REORDERED_EFFECT.value,
        EffectsErrorsFamily.AUDIT_OMISSION.value,
        EffectsErrorsFamily.SUCCESS_BEFORE_OBSERVATION.value,
        EffectsErrorsFamily.MISSING_COMPENSATION.value,
    }
)

REQUIRED_ERROR_RETRY_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        EffectsErrorsFamily.SWALLOWED_FAILURE.value,
        EffectsErrorsFamily.MISCLASSIFIED_FAILURE.value,
        EffectsErrorsFamily.UNAVAILABLE_TO_SUCCESS.value,
        EffectsErrorsFamily.RETRY_BUDGET.value,
        EffectsErrorsFamily.CANCELLATION.value,
        EffectsErrorsFamily.INTEGRITY_FAILURE.value,
    }
)

_SIDE_EFFECT_ONLY_FAMILIES: Final[frozenset[str]] = REQUIRED_SIDE_EFFECT_FAMILIES
_ERROR_RETRY_ONLY_FAMILIES: Final[frozenset[str]] = REQUIRED_ERROR_RETRY_FAMILIES


# ---------------------------------------------------------------------------
# Spec / recipe types
# ---------------------------------------------------------------------------


def _normalize_operator_class(value: OperatorClass | str) -> str:
    if isinstance(value, OperatorClass):
        class_value = value.value
    elif type(value) is str:
        try:
            class_value = OperatorClass(value).value
        except ValueError as exc:
            raise EffectsErrorsError(
                f"unsupported operator_class: {value!r}"
            ) from exc
    else:
        raise EffectsErrorsError(
            "operator_class must be OperatorClass or str"
        )
    if class_value not in ADMITTED_OPERATOR_CLASSES:
        raise EffectsErrorsError(
            "operator_class must be side_effect or error_retry; "
            f"got {class_value!r}"
        )
    return class_value


def _default_operator_class_for_family(family: str) -> str:
    if family in _SIDE_EFFECT_ONLY_FAMILIES:
        return OperatorClass.SIDE_EFFECT.value
    if family in _ERROR_RETRY_ONLY_FAMILIES:
        return OperatorClass.ERROR_RETRY.value
    raise EffectsErrorsError(f"unsupported family for class default: {family!r}")


def _default_risk_for_class(operator_class: str) -> str:
    if operator_class == OperatorClass.SIDE_EFFECT.value:
        return DEFAULT_SIDE_EFFECT_RISK_CLASS
    return DEFAULT_ERROR_RETRY_RISK_CLASS


@dataclass(frozen=True, slots=True)
class EffectsErrorsOperatorSpec:
    """Declarative recipe for one sealed side-effect or error/retry operator.

    Specs are pure data used to construct ``MutationOperatorDefinition``
    values. They are not durable CAS records.
    """

    operator_id: str
    family: EffectsErrorsFamily | str
    semantic_intent: str
    syntactic_transformation: str
    expected_violated_property_classes: Sequence[PropertyClass | str]
    likely_equivalent_conditions: Sequence[str] = ()
    operator_class: OperatorClass | str | None = None
    risk_class: MutationRiskClass | str | None = None
    max_mutants_per_target: int = _DEFAULT_MAX_MUTANTS_PER_TARGET
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.operator_id) is not str or not self.operator_id.strip():
            raise EffectsErrorsError("operator_id must be a nonempty string")

        family = self.family
        if isinstance(family, EffectsErrorsFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = EffectsErrorsFamily(family).value
            except ValueError as exc:
                raise EffectsErrorsError(
                    f"unsupported side-effect/error-retry family: {family!r}"
                ) from exc
        else:
            raise EffectsErrorsError(
                "family must be EffectsErrorsFamily or str"
            )
        object.__setattr__(self, "family", family_value)

        if self.operator_class is None:
            class_value = _default_operator_class_for_family(family_value)
        else:
            class_value = _normalize_operator_class(self.operator_class)
        if family_value in _SIDE_EFFECT_ONLY_FAMILIES and (
            class_value != OperatorClass.SIDE_EFFECT.value
        ):
            raise EffectsErrorsError(
                f"family {family_value!r} requires operator_class side_effect"
            )
        if family_value in _ERROR_RETRY_ONLY_FAMILIES and (
            class_value != OperatorClass.ERROR_RETRY.value
        ):
            raise EffectsErrorsError(
                f"family {family_value!r} requires operator_class error_retry"
            )
        object.__setattr__(self, "operator_class", class_value)

        if self.risk_class is None:
            risk_value = _default_risk_for_class(class_value)
        else:
            risk = self.risk_class
            if isinstance(risk, MutationRiskClass):
                risk_value = risk.value
            elif type(risk) is str:
                try:
                    risk_value = MutationRiskClass(risk).value
                except ValueError as exc:
                    raise EffectsErrorsError(
                        f"unsupported risk_class: {risk!r}"
                    ) from exc
            else:
                raise EffectsErrorsError(
                    "risk_class must be MutationRiskClass or str"
                )
        object.__setattr__(self, "risk_class", risk_value)

        if type(self.semantic_intent) is not str or not self.semantic_intent.strip():
            raise EffectsErrorsError("semantic_intent must be nonempty")
        if (
            type(self.syntactic_transformation) is not str
            or not self.syntactic_transformation.strip()
        ):
            raise EffectsErrorsError("syntactic_transformation must be nonempty")

        props = tuple(self.expected_violated_property_classes)
        if not props:
            raise EffectsErrorsError(
                "expected_violated_property_classes must not be empty"
            )
        object.__setattr__(self, "expected_violated_property_classes", props)

        equiv = tuple(self.likely_equivalent_conditions or ())
        if not equiv:
            raise EffectsErrorsError(
                "likely_equivalent_conditions must provide equivalence hints"
            )
        for condition in equiv:
            if type(condition) is not str or not condition.strip():
                raise EffectsErrorsError(
                    "likely_equivalent_conditions entries must be nonempty strings"
                )
        object.__setattr__(self, "likely_equivalent_conditions", equiv)

        if (
            type(self.max_mutants_per_target) is not int
            or isinstance(self.max_mutants_per_target, bool)
            or self.max_mutants_per_target < 1
        ):
            raise EffectsErrorsError(
                "max_mutants_per_target must be a positive integer"
            )

        meta = dict(self.metadata or {})
        meta.setdefault(_FAMILY_METADATA_KEY, family_value)
        meta.setdefault(_OPERATOR_CLASS_METADATA_KEY, class_value)
        try:
            reject_private_model_authority_and_host_fallbacks(
                meta, path="EffectsErrorsOperatorSpec.metadata"
            )
            cid_for_structured(meta)
        except Exception as exc:  # noqa: BLE001
            raise EffectsErrorsError(
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


def assert_effects_errors_operator_defaults(
    operator: MutationOperatorDefinition,
) -> None:
    """Fail closed when an operator lacks class, intent, or property defaults."""

    if not isinstance(operator, MutationOperatorDefinition):
        raise EffectsErrorsError(
            "operator must be a sealed MutationOperatorDefinition"
        )
    if operator.operator_class not in ADMITTED_OPERATOR_CLASSES:
        raise EffectsErrorsError(
            "operator_class must be side_effect or error_retry"
        )
    if not operator.semantic_intent or not str(operator.semantic_intent).strip():
        raise EffectsErrorsError(
            f"operator {operator.operator_id} must declare semantic_intent"
        )
    if not operator.likely_equivalent_conditions:
        raise EffectsErrorsError(
            f"operator {operator.operator_id} must declare equivalence hints "
            "(likely_equivalent_conditions)"
        )

    props = set(operator.expected_violated_property_classes)
    if operator.operator_class == OperatorClass.SIDE_EFFECT.value:
        allowed = {
            PropertyClass.SIDE_EFFECT_OBLIGATION.value,
            PropertyClass.COMPENSATION.value,
            PropertyClass.DATA_INTEGRITY.value,
            PropertyClass.DURABILITY.value,
            PropertyClass.IDEMPOTENCY.value,
            PropertyClass.STATE_TRANSITION.value,
        }
        if not (props & allowed):
            raise EffectsErrorsError(
                f"operator {operator.operator_id} must expect a side-effect-"
                "related property violation "
                f"(one of {sorted(allowed)})"
            )
        if PropertyClass.SIDE_EFFECT_OBLIGATION.value not in props:
            # Side-effect-class operators must always list the obligation class.
            # Compensation-only mutants still violate the effect obligation.
            if PropertyClass.COMPENSATION.value not in props:
                raise EffectsErrorsError(
                    f"operator {operator.operator_id} must expect "
                    "side_effect_obligation or compensation property violations"
                )
    else:
        allowed = {
            PropertyClass.ERROR_HANDLING.value,
            PropertyClass.RETRY_BUDGET.value,
            PropertyClass.CANCELLATION.value,
            PropertyClass.DATA_INTEGRITY.value,
            PropertyClass.STORAGE_INTEGRITY.value,
            PropertyClass.SIDE_EFFECT_OBLIGATION.value,
            PropertyClass.COMPENSATION.value,
        }
        if not (props & allowed):
            raise EffectsErrorsError(
                f"operator {operator.operator_id} must expect an error/retry-"
                "related property violation "
                f"(one of {sorted(allowed)})"
            )


def build_effects_errors_operator(
    spec: EffectsErrorsOperatorSpec,
    *,
    supported_languages: Sequence[str] | None = None,
    supported_artifact_types: Sequence[str] | None = None,
    target_prerequisites: Sequence[str] | None = None,
    scope_limits: ScopeLimits | None = None,
    rollback: RollbackDeclaration | None = None,
    required_sandbox: SandboxRequirement | None = None,
    operator_version: str = EFFECTS_ERRORS_OPERATOR_VERSION,
) -> MutationOperatorDefinition:
    """Seal one side-effect or error/retry operator under defaults."""

    if not isinstance(spec, EffectsErrorsOperatorSpec):
        raise EffectsErrorsError("spec must be an EffectsErrorsOperatorSpec")
    definition = MutationOperatorDefinition(
        operator_id=spec.operator_id,
        operator_version=operator_version,
        operator_class=spec.operator_class,
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
        raise EffectsErrorsError(str(exc)) from exc
    assert_effects_errors_operator_defaults(sealed)
    return sealed


# ---------------------------------------------------------------------------
# Normative catalogue recipes (plan acceptance families)
# ---------------------------------------------------------------------------


def effects_errors_operator_specs() -> tuple[EffectsErrorsOperatorSpec, ...]:
    """Return the closed, ordered set of normative operator recipes."""

    obligation = PropertyClass.SIDE_EFFECT_OBLIGATION
    compensation = PropertyClass.COMPENSATION
    data_int = PropertyClass.DATA_INTEGRITY
    durability = PropertyClass.DURABILITY
    idempotency = PropertyClass.IDEMPOTENCY
    error_handling = PropertyClass.ERROR_HANDLING
    retry_budget = PropertyClass.RETRY_BUDGET
    cancellation = PropertyClass.CANCELLATION
    storage_int = PropertyClass.STORAGE_INTEGRITY

    return (
        # --- omitted effect --------------------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="se_omit_required_write",
            family=EffectsErrorsFamily.OMITTED_EFFECT,
            semantic_intent=(
                "Omit a required durable write or side-effect call so success "
                "is reported without the obligated external mutation"
            ),
            syntactic_transformation="remove_required_side_effect_call",
            expected_violated_property_classes=(obligation, durability),
            likely_equivalent_conditions=(
                "write_is_already_satisfied_on_all_paths",
                "side_effect_is_optional_by_contract",
                "observer_does_not_check_effect_presence",
            ),
            notes="Missing required write/effect",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="se_omit_ack_publication",
            family=EffectsErrorsFamily.OMITTED_EFFECT,
            semantic_intent=(
                "Skip publication of an acknowledgement, receipt, or outbox "
                "record that observers require to treat work as complete"
            ),
            syntactic_transformation="omit_ack_or_receipt_publication",
            expected_violated_property_classes=(obligation, durability),
            likely_equivalent_conditions=(
                "ack_is_derived_elsewhere",
                "no_observer_requires_publication",
            ),
            notes="Omit ack/receipt publication",
        ),
        # --- wrong effect ----------------------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="se_wrong_write_target",
            family=EffectsErrorsFamily.WRONG_EFFECT,
            semantic_intent=(
                "Redirect a write or effect to the wrong target (key, path, "
                "topic, or tenant) while keeping the call shape valid"
            ),
            syntactic_transformation="replace_effect_target_with_wrong_key",
            expected_violated_property_classes=(obligation, data_int),
            likely_equivalent_conditions=(
                "wrong_target_aliases_correct_target",
                "target_is_never_read_by_observers",
            ),
            notes="Wrong write/effect target",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="se_wrong_effect_payload",
            family=EffectsErrorsFamily.WRONG_EFFECT,
            semantic_intent=(
                "Substitute a type-valid but semantically wrong payload into a "
                "side-effect call so observers accept corrupted content"
            ),
            syntactic_transformation="replace_effect_payload_with_wrong_value",
            expected_violated_property_classes=(obligation, data_int),
            likely_equivalent_conditions=(
                "payload_is_ignored_by_consumers",
                "wrong_payload_is_observationally_identical",
            ),
            notes="Wrong effect payload",
        ),
        # --- early effect ----------------------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="se_effect_before_validation",
            family=EffectsErrorsFamily.EARLY_EFFECT,
            semantic_intent=(
                "Execute a durable side effect before validation or authority "
                "checks complete, so invalid work still mutates state"
            ),
            syntactic_transformation="move_side_effect_before_validation",
            expected_violated_property_classes=(obligation, data_int),
            likely_equivalent_conditions=(
                "validation_always_succeeds",
                "effect_is_idempotent_and_rolled_back_on_failure",
            ),
            notes="Effect before validation",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="se_effect_before_commit_gate",
            family=EffectsErrorsFamily.EARLY_EFFECT,
            semantic_intent=(
                "Perform a committed-looking side effect before the commit or "
                "fencing gate that authorizes durability"
            ),
            syntactic_transformation="move_side_effect_before_commit_gate",
            expected_violated_property_classes=(obligation, durability),
            likely_equivalent_conditions=(
                "commit_gate_is_always_open",
                "early_effect_is_shadowed_by_true_commit",
            ),
            notes="Effect before commit gate",
        ),
        # --- double effect ---------------------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="se_double_write",
            family=EffectsErrorsFamily.DOUBLE_EFFECT,
            semantic_intent=(
                "Duplicate a non-idempotent side effect so the same write or "
                "action executes twice for a single logical operation"
            ),
            syntactic_transformation="duplicate_side_effect_call",
            expected_violated_property_classes=(obligation, idempotency),
            likely_equivalent_conditions=(
                "effect_is_fully_idempotent",
                "duplicate_is_deduplicated_by_downstream",
            ),
            notes="Double non-idempotent write",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="se_retry_without_dedup",
            family=EffectsErrorsFamily.DOUBLE_EFFECT,
            semantic_intent=(
                "Allow a retry path to re-apply a side effect without "
                "idempotency keys or deduplication, producing double execution"
            ),
            syntactic_transformation="retry_side_effect_without_idempotency_key",
            expected_violated_property_classes=(obligation, idempotency),
            likely_equivalent_conditions=(
                "retries_never_occur",
                "downstream_deduplicates_by_content",
            ),
            notes="Retry without dedup/idempotency",
        ),
        # --- reordered effect ------------------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="se_reorder_writes",
            family=EffectsErrorsFamily.REORDERED_EFFECT,
            semantic_intent=(
                "Reorder two dependent side effects so observers see an "
                "illegal intermediate or inverted commit order"
            ),
            syntactic_transformation="permute_dependent_side_effect_order",
            expected_violated_property_classes=(obligation, data_int),
            likely_equivalent_conditions=(
                "effects_are_commutative",
                "observers_never_read_between_effects",
            ),
            notes="Reorder dependent writes",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="se_reorder_release_before_publish",
            family=EffectsErrorsFamily.REORDERED_EFFECT,
            semantic_intent=(
                "Publish or release a resource before the preceding write that "
                "the release is meant to make visible"
            ),
            syntactic_transformation="swap_publish_before_write_completion",
            expected_violated_property_classes=(obligation, durability),
            likely_equivalent_conditions=(
                "publish_is_atomic_with_write",
                "readers_retry_until_content_present",
            ),
            notes="Release/publish before write completes",
        ),
        # --- audit omission --------------------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="se_omit_audit_log",
            family=EffectsErrorsFamily.AUDIT_OMISSION,
            semantic_intent=(
                "Omit a required audit-log or trail entry for a sensitive "
                "mutation so the action is not attributable"
            ),
            syntactic_transformation="remove_audit_log_write",
            expected_violated_property_classes=(obligation,),
            likely_equivalent_conditions=(
                "audit_is_optional_by_policy",
                "audit_is_emitted_by_outer_middleware",
            ),
            notes="Skip audit log write",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="se_suppress_security_event",
            family=EffectsErrorsFamily.AUDIT_OMISSION,
            semantic_intent=(
                "Suppress emission of a security or compliance event that "
                "must accompany authorization-sensitive side effects"
            ),
            syntactic_transformation="drop_security_event_emission",
            expected_violated_property_classes=(obligation,),
            likely_equivalent_conditions=(
                "event_stream_is_not_monitored",
                "duplicate_event_exists_elsewhere",
            ),
            notes="Suppress security/compliance event",
        ),
        # --- success before observation --------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="se_success_before_durability_observe",
            family=EffectsErrorsFamily.SUCCESS_BEFORE_OBSERVATION,
            semantic_intent=(
                "Return success to the caller before durability or observer "
                "confirmation of the required side effect"
            ),
            syntactic_transformation="return_success_before_durability_observation",
            expected_violated_property_classes=(obligation, durability),
            likely_equivalent_conditions=(
                "effect_is_synchronous_and_already_durable",
                "caller_does_not_rely_on_durability_guarantee",
            ),
            notes="Success before durability observation",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="se_ack_before_effect_complete",
            family=EffectsErrorsFamily.SUCCESS_BEFORE_OBSERVATION,
            semantic_intent=(
                "Acknowledge completion to upstream before the obligated "
                "side effect has finished or been observed"
            ),
            syntactic_transformation="send_ack_before_side_effect_completion",
            expected_violated_property_classes=(obligation, durability),
            likely_equivalent_conditions=(
                "ack_is_explicitly_at_least_once_by_contract",
                "effect_completion_is_guaranteed_by_runtime",
            ),
            notes="Ack before effect complete",
        ),
        # --- missing compensation --------------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="se_skip_compensation_on_partial_failure",
            family=EffectsErrorsFamily.MISSING_COMPENSATION,
            semantic_intent=(
                "Skip compensation or rollback after a partial multi-step "
                "mutation so prior effects remain applied"
            ),
            syntactic_transformation="omit_compensation_on_partial_failure",
            expected_violated_property_classes=(obligation, compensation),
            likely_equivalent_conditions=(
                "partial_failure_never_occurs",
                "prior_effects_are_already_idempotent_no_ops",
            ),
            notes="No compensation after partial failure",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="se_incomplete_compensation",
            family=EffectsErrorsFamily.MISSING_COMPENSATION,
            semantic_intent=(
                "Run only a subset of required compensating actions so some "
                "side effects remain unreverted after failure"
            ),
            syntactic_transformation="drop_subset_of_compensation_actions",
            expected_violated_property_classes=(compensation, obligation),
            likely_equivalent_conditions=(
                "dropped_actions_are_redundant",
                "external_systems_self-heal",
            ),
            notes="Incomplete compensation set",
        ),
        # --- swallowed failure -----------------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="er_swallow_exception",
            family=EffectsErrorsFamily.SWALLOWED_FAILURE,
            semantic_intent=(
                "Catch and discard an exception without re-raise, typed "
                "failure result, or error propagation to the caller"
            ),
            syntactic_transformation="replace_except_body_with_pass_or_continue",
            expected_violated_property_classes=(error_handling,),
            likely_equivalent_conditions=(
                "exception_class_is_never_raised",
                "caller_treats_success_and_failure_identically",
            ),
            notes="Swallow exception",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="er_silent_error_to_none",
            family=EffectsErrorsFamily.SWALLOWED_FAILURE,
            semantic_intent=(
                "Map a failure path to None/empty success without recording "
                "or surfacing the error condition"
            ),
            syntactic_transformation="return_none_or_empty_on_error_path",
            expected_violated_property_classes=(error_handling,),
            likely_equivalent_conditions=(
                "none_is_the_documented_failure_sentinel",
                "error_path_is_statically_unreachable",
            ),
            notes="Silent error becomes empty success",
        ),
        # --- misclassified failure -------------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="er_misclassify_error_code",
            family=EffectsErrorsFamily.MISCLASSIFIED_FAILURE,
            semantic_intent=(
                "Map a failure to the wrong error code or exception type so "
                "callers apply incorrect recovery or authorization logic"
            ),
            syntactic_transformation="replace_error_code_or_exception_type",
            expected_violated_property_classes=(error_handling,),
            likely_equivalent_conditions=(
                "all_error_codes_share_identical_handling",
                "misclassified_code_is_never_produced",
            ),
            notes="Wrong error classification",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="er_treat_fatal_as_retryable",
            family=EffectsErrorsFamily.MISCLASSIFIED_FAILURE,
            semantic_intent=(
                "Classify a fatal or non-retryable failure as retryable so "
                "the system loops instead of failing closed"
            ),
            syntactic_transformation="mark_fatal_error_as_retryable",
            expected_violated_property_classes=(error_handling, retry_budget),
            likely_equivalent_conditions=(
                "fatal_errors_never_occur",
                "retry_policy_already_caps_fatal_classes",
            ),
            notes="Fatal treated as retryable",
        ),
        # --- unavailable/unknown to success/allow ----------------------------
        EffectsErrorsOperatorSpec(
            operator_id="er_unavailable_to_success",
            family=EffectsErrorsFamily.UNAVAILABLE_TO_SUCCESS,
            semantic_intent=(
                "Treat an unavailable or unknown dependency status as success "
                "so degraded or missing backends appear healthy"
            ),
            syntactic_transformation="map_unavailable_status_to_success",
            expected_violated_property_classes=(error_handling,),
            likely_equivalent_conditions=(
                "dependency_is_always_available",
                "unavailable_is_defined_as_success_by_contract",
            ),
            notes="Unavailable becomes success",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="er_unknown_to_allow",
            family=EffectsErrorsFamily.UNAVAILABLE_TO_SUCCESS,
            semantic_intent=(
                "Default unknown or indeterminate outcomes to allow/success "
                "instead of fail-closed denial"
            ),
            syntactic_transformation="map_unknown_outcome_to_allow",
            expected_violated_property_classes=(error_handling,),
            likely_equivalent_conditions=(
                "unknown_never_occurs",
                "policy_explicitly_allows_unknown",
            ),
            notes="Unknown becomes allow",
        ),
        # --- retry budget ----------------------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="er_remove_retry_budget",
            family=EffectsErrorsFamily.RETRY_BUDGET,
            semantic_intent=(
                "Remove or zero a retry budget so transient failures never "
                "retry when the contract requires bounded retries"
            ),
            syntactic_transformation="set_retry_budget_to_zero_or_remove",
            expected_violated_property_classes=(retry_budget, error_handling),
            likely_equivalent_conditions=(
                "operations_never_need_retry",
                "outer_layer_already_retries_identically",
            ),
            notes="Missing/zero retry budget",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="er_unbounded_retries",
            family=EffectsErrorsFamily.RETRY_BUDGET,
            semantic_intent=(
                "Remove the upper bound on retries so failures may loop "
                "without a finite budget or deadline"
            ),
            syntactic_transformation="remove_max_retry_or_deadline_bound",
            expected_violated_property_classes=(retry_budget,),
            likely_equivalent_conditions=(
                "underlying_call_always_succeeds_first_try",
                "process_lifetime_already_caps_retries",
            ),
            notes="Unbounded retries",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="er_ignore_retry_after",
            family=EffectsErrorsFamily.RETRY_BUDGET,
            semantic_intent=(
                "Ignore retry-after or backoff guidance so retries fire "
                "immediately and exhaust budget unsafely"
            ),
            syntactic_transformation="skip_backoff_or_retry_after_delay",
            expected_violated_property_classes=(retry_budget, error_handling),
            likely_equivalent_conditions=(
                "retry_after_is_always_zero",
                "server_tolerates_immediate_retry",
            ),
            notes="Ignore backoff/retry-after",
        ),
        # --- cancellation ----------------------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="er_ignore_cancellation_signal",
            family=EffectsErrorsFamily.CANCELLATION,
            semantic_intent=(
                "Ignore a cooperative cancellation signal so work continues "
                "after the caller requested stop"
            ),
            syntactic_transformation="replace_cancellation_check_with_false",
            expected_violated_property_classes=(cancellation, error_handling),
            likely_equivalent_conditions=(
                "cancellation_never_signalled",
                "operation_is_atomic_and_uninterruptible_by_contract",
            ),
            notes="Ignore cancellation signal",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="er_cancel_without_cleanup",
            family=EffectsErrorsFamily.CANCELLATION,
            semantic_intent=(
                "Take the cancellation exit without cleanup, compensation, "
                "or resource-release obligations"
            ),
            syntactic_transformation="return_on_cancel_before_cleanup",
            expected_violated_property_classes=(
                cancellation,
                compensation,
                obligation,
            ),
            likely_equivalent_conditions=(
                "no_resources_held_at_cancel_point",
                "cleanup_is_guaranteed_by_scope_exit",
            ),
            notes="Cancel without cleanup",
        ),
        # --- integrity failure / bypass --------------------------------------
        EffectsErrorsOperatorSpec(
            operator_id="er_bypass_integrity_check",
            family=EffectsErrorsFamily.INTEGRITY_FAILURE,
            semantic_intent=(
                "Bypass a checksum, hash, signature, or integrity gate so "
                "tampered or corrupt payloads proceed as valid"
            ),
            syntactic_transformation="skip_integrity_or_checksum_verification",
            expected_violated_property_classes=(data_int, storage_int),
            likely_equivalent_conditions=(
                "payloads_are_always_pristine",
                "integrity_is_enforced_at_a_stronger_outer_boundary",
            ),
            notes="Bypass integrity verification",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="er_accept_integrity_failure",
            family=EffectsErrorsFamily.INTEGRITY_FAILURE,
            semantic_intent=(
                "Treat a failed integrity check as success or soft warning "
                "instead of failing closed"
            ),
            syntactic_transformation="map_integrity_failure_to_success",
            expected_violated_property_classes=(data_int, storage_int, error_handling),
            likely_equivalent_conditions=(
                "integrity_failures_never_occur",
                "degraded_mode_is_explicitly_authorized",
            ),
            notes="Accept integrity failure as success",
        ),
        EffectsErrorsOperatorSpec(
            operator_id="er_strip_integrity_metadata",
            family=EffectsErrorsFamily.INTEGRITY_FAILURE,
            semantic_intent=(
                "Strip or zero integrity metadata (hash, MAC, length) so "
                "downstream verification cannot detect corruption"
            ),
            syntactic_transformation="clear_or_remove_integrity_metadata",
            expected_violated_property_classes=(data_int, storage_int),
            likely_equivalent_conditions=(
                "downstream_does_not_verify_metadata",
                "metadata_is_recomputed_from_trusted_source",
            ),
            notes="Strip integrity metadata",
        ),
    )


# ---------------------------------------------------------------------------
# Operator handles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EffectsErrorsOperator(MutationOperator):
    """Declaration-backed side-effect or error/retry operator with family binding.

    Interface membership: ``SideEffectErrorRetryMutationOperators@1`` catalogue
    entry. Does not generate source rewrites; generation is owned by AAE-022.
    """

    _definition: MutationOperatorDefinition
    family: str
    spec_operator_id: str

    def __post_init__(self) -> None:
        sealed = canonicalize_operator_declaration(self._definition)
        assert_effects_errors_operator_defaults(sealed)
        if sealed.operator_class not in ADMITTED_OPERATOR_CLASSES:
            raise EffectsErrorsError(
                "EffectsErrorsOperator requires operator_class "
                "side_effect or error_retry"
            )
        try:
            family_value = EffectsErrorsFamily(self.family).value
        except ValueError as exc:
            raise EffectsErrorsError(
                f"unsupported side-effect/error-retry family: {self.family!r}"
            ) from exc
        meta_family = sealed.metadata.get(_FAMILY_METADATA_KEY)
        if meta_family is not None and meta_family != family_value:
            raise EffectsErrorsError(
                "definition metadata ee_family does not match family binding "
                f"({meta_family!r} != {family_value!r})"
            )
        meta_class = sealed.metadata.get(_OPERATOR_CLASS_METADATA_KEY)
        if meta_class is not None and meta_class != sealed.operator_class:
            raise EffectsErrorsError(
                "definition metadata ee_operator_class does not match "
                f"operator_class ({meta_class!r} != {sealed.operator_class!r})"
            )
        # Family / class coherence on the handle
        if family_value in _SIDE_EFFECT_ONLY_FAMILIES and (
            sealed.operator_class != OperatorClass.SIDE_EFFECT.value
        ):
            raise EffectsErrorsError(
                f"family {family_value!r} requires operator_class side_effect"
            )
        if family_value in _ERROR_RETRY_ONLY_FAMILIES and (
            sealed.operator_class != OperatorClass.ERROR_RETRY.value
        ):
            raise EffectsErrorsError(
                f"family {family_value!r} requires operator_class error_retry"
            )
        object.__setattr__(self, "_definition", sealed)
        object.__setattr__(self, "family", family_value)
        if type(self.spec_operator_id) is not str or not self.spec_operator_id:
            raise EffectsErrorsError("spec_operator_id must be nonempty")
        if self.spec_operator_id != sealed.operator_id:
            raise EffectsErrorsError(
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
        raise EffectsErrorsError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise EffectsErrorsError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    return dict(data)


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise EffectsErrorsError(f"{name} must be a nonempty trimmed string")
    return value


@dataclass(frozen=True, slots=True)
class EffectsErrorsMutationOperators:
    """Immutable catalogue of sealed side-effect and error/retry operators.

    Interface: ``SideEffectErrorRetryMutationOperators@1``
    """

    operators: Sequence[EffectsErrorsOperator]
    producer_id: str = EFFECTS_ERRORS_OPERATORS_PRODUCER
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
            "operator_classes",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.operators, Sequence) or isinstance(
            self.operators, (str, bytes)
        ):
            raise EffectsErrorsError(
                "operators must be a sequence of EffectsErrorsOperator"
            )
        sealed: list[EffectsErrorsOperator] = []
        seen_ids: set[str] = set()
        seen_cids: set[str] = set()
        families: set[str] = set()
        classes: set[str] = set()
        for item in self.operators:
            if not isinstance(item, EffectsErrorsOperator):
                raise EffectsErrorsError(
                    "operators entries must be EffectsErrorsOperator"
                )
            definition = item.definition
            assert_effects_errors_operator_defaults(definition)
            try:
                assert_operator_bounded(definition)
            except OperatorBoundError as exc:
                raise EffectsErrorsError(str(exc)) from exc
            if definition.operator_id in seen_ids:
                raise EffectsErrorsError(
                    f"duplicate operator_id in catalogue: {definition.operator_id}"
                )
            if definition.operator_cid in seen_cids:
                raise EffectsErrorsError(
                    f"duplicate operator_cid in catalogue: {definition.operator_cid}"
                )
            seen_ids.add(definition.operator_id)
            seen_cids.add(definition.operator_cid)
            families.add(item.family)
            classes.add(definition.operator_class)
            sealed.append(item)

        missing = REQUIRED_EFFECTS_ERRORS_FAMILIES - families
        if missing:
            raise EffectsErrorsCoverageError(
                "side-effect/error-retry catalogue missing required families: "
                + ", ".join(sorted(missing))
            )
        missing_classes = ADMITTED_OPERATOR_CLASSES - classes
        if missing_classes:
            raise EffectsErrorsCoverageError(
                "side-effect/error-retry catalogue missing required operator "
                "classes: " + ", ".join(sorted(missing_classes))
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
                meta_payload, path="EffectsErrorsMutationOperators.metadata"
            )
            cid_for_structured(meta_payload)
        except Exception as exc:  # noqa: BLE001
            raise EffectsErrorsError(
                "metadata must be DAG-JSON structured data without model authority"
            ) from exc
        object.__setattr__(self, "metadata", MappingProxyType(meta_payload))

        computed = cid_for_structured(self._identity_payload_without_catalogue_id())
        if self.catalogue_id is None:
            object.__setattr__(self, "catalogue_id", computed)
        else:
            claimed = _text(self.catalogue_id, "catalogue_id")
            if claimed != computed:
                raise EffectsErrorsError(
                    "catalogue_id identity mismatch with recomputed catalogue identity"
                )
            object.__setattr__(self, "catalogue_id", claimed)

    def _identity_payload_without_catalogue_id(self) -> dict[str, Any]:
        return {
            "schema": EFFECTS_ERRORS_OPERATORS_SCHEMA,
            "interface_id": EFFECTS_ERRORS_OPERATORS_INTERFACE,
            "catalogue_version": EFFECTS_ERRORS_OPERATORS_VERSION,
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
            "operator_classes": sorted(
                {item.definition.operator_class for item in self.operators}
            ),
        }

    def identity_payload(self) -> dict[str, Any]:
        payload = self._identity_payload_without_catalogue_id()
        payload["catalogue_id"] = self.catalogue_id
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EFFECTS_ERRORS_OPERATORS_SCHEMA,
            "interface_id": EFFECTS_ERRORS_OPERATORS_INTERFACE,
            "catalogue_version": EFFECTS_ERRORS_OPERATORS_VERSION,
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
            "operator_classes": sorted(
                {item.definition.operator_class for item in self.operators}
            ),
            "catalogue_id": self.catalogue_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EffectsErrorsMutationOperators":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != EFFECTS_ERRORS_OPERATORS_SCHEMA:
            raise EffectsErrorsError(
                "unsupported EffectsErrorsMutationOperators schema version"
            )
        if payload.pop("interface_id") != EFFECTS_ERRORS_OPERATORS_INTERFACE:
            raise EffectsErrorsError(
                "unsupported EffectsErrorsMutationOperators interface_id"
            )
        version = payload.pop(
            "catalogue_version", EFFECTS_ERRORS_OPERATORS_VERSION
        )
        if version != EFFECTS_ERRORS_OPERATORS_VERSION:
            raise EffectsErrorsError(
                "unsupported EffectsErrorsMutationOperators catalogue_version"
            )
        payload.pop("operator_cids", None)
        payload.pop("operator_count", None)
        payload.pop("families", None)
        payload.pop("operator_classes", None)
        raw_ops = payload["operators"]
        if not isinstance(raw_ops, list):
            raise EffectsErrorsError("operators must be a list")
        operators: list[EffectsErrorsOperator] = []
        for entry in raw_ops:
            if not isinstance(entry, Mapping):
                raise EffectsErrorsError(
                    "operators entries must be mappings with family and definition"
                )
            definition_raw = entry.get("definition")
            if isinstance(definition_raw, MutationOperatorDefinition):
                definition = definition_raw
            elif isinstance(definition_raw, Mapping):
                definition = MutationOperatorDefinition.from_dict(definition_raw)
            else:
                raise EffectsErrorsError(
                    "operators[].definition must be MutationOperatorDefinition or mapping"
                )
            family = entry.get("family")
            if family is None:
                family = definition.metadata.get(_FAMILY_METADATA_KEY)
            spec_id = entry.get("spec_operator_id", definition.operator_id)
            operators.append(
                EffectsErrorsOperator(
                    _definition=definition,
                    family=family,
                    spec_operator_id=spec_id,
                )
            )
        return cls(
            operators=operators,
            producer_id=payload.get(
                "producer_id", EFFECTS_ERRORS_OPERATORS_PRODUCER
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
        if isinstance(item, EffectsErrorsOperator):
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

    def operator_classes(self) -> tuple[str, ...]:
        return tuple(
            sorted({item.definition.operator_class for item in self.operators})
        )

    def definitions(self) -> tuple[MutationOperatorDefinition, ...]:
        return tuple(item.definition for item in self.operators)

    def list_operators(self) -> tuple[EffectsErrorsOperator, ...]:
        return tuple(self.operators)

    def operators_for_family(
        self, family: EffectsErrorsFamily | str
    ) -> tuple[EffectsErrorsOperator, ...]:
        if isinstance(family, EffectsErrorsFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = EffectsErrorsFamily(family).value
            except ValueError as exc:
                raise EffectsErrorsError(
                    f"unsupported side-effect/error-retry family: {family!r}"
                ) from exc
        else:
            raise EffectsErrorsError(
                "family must be EffectsErrorsFamily or str"
            )
        return tuple(item for item in self.operators if item.family == family_value)

    def operators_for_class(
        self, operator_class: OperatorClass | str
    ) -> tuple[EffectsErrorsOperator, ...]:
        class_value = _normalize_operator_class(operator_class)
        return tuple(
            item
            for item in self.operators
            if item.definition.operator_class == class_value
        )

    def get(
        self,
        operator_id: str,
        operator_version: str | None = None,
    ) -> EffectsErrorsOperator:
        operator_id = _text(operator_id, "operator_id")
        matches = [
            item for item in self.operators if item.operator_id == operator_id
        ]
        if not matches:
            raise EffectsErrorsError(f"unknown operator_id: {operator_id}")
        if operator_version is None:
            if len(matches) != 1:
                versions = ", ".join(
                    sorted({item.operator_version for item in matches})
                )
                raise EffectsErrorsError(
                    f"operator_id {operator_id} is ambiguous across versions "
                    f"({versions}); provide operator_version"
                )
            return matches[0]
        operator_version = _text(operator_version, "operator_version")
        for item in matches:
            if item.operator_version == operator_version:
                return item
        raise EffectsErrorsError(
            f"unknown operator: {operator_id}@{operator_version}"
        )

    def get_by_cid(self, operator_cid: str) -> EffectsErrorsOperator:
        operator_cid = _text(operator_cid, "operator_cid")
        for item in self.operators:
            if item.operator_cid == operator_cid:
                return item
        raise EffectsErrorsError(f"unknown operator_cid: {operator_cid}")

    def operators_for_target(
        self, target: MutationTarget
    ) -> tuple[EffectsErrorsOperator, ...]:
        if not isinstance(target, MutationTarget):
            raise EffectsErrorsError("target must be a MutationTarget")
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
                producer_id=producer_id or EFFECTS_ERRORS_OPERATORS_PRODUCER,
                notes=notes if notes is not None else self.notes,
                metadata=metadata if metadata is not None else dict(self.metadata),
            )
        except OperatorRegistryError as exc:
            raise EffectsErrorsError(str(exc)) from exc

    def register_into(
        self, builder: MutationOperatorRegistryBuilder
    ) -> tuple[MutationOperatorDefinition, ...]:
        """Admit every catalogue operator into a mutable registry builder."""

        if not isinstance(builder, MutationOperatorRegistryBuilder):
            raise EffectsErrorsError(
                "builder must be a MutationOperatorRegistryBuilder"
            )
        sealed: list[MutationOperatorDefinition] = []
        for item in self.operators:
            try:
                sealed.append(builder.register(item.definition))
            except OperatorRegistryError as exc:
                raise EffectsErrorsError(str(exc)) from exc
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
        """Re-check that every required family and class is present."""

        present = set(self.families())
        missing = REQUIRED_EFFECTS_ERRORS_FAMILIES - present
        if missing:
            raise EffectsErrorsCoverageError(
                "side-effect/error-retry catalogue missing required families: "
                + ", ".join(sorted(missing))
            )
        missing_classes = ADMITTED_OPERATOR_CLASSES - set(self.operator_classes())
        if missing_classes:
            raise EffectsErrorsCoverageError(
                "side-effect/error-retry catalogue missing required operator "
                "classes: " + ", ".join(sorted(missing_classes))
            )
        if not (REQUIRED_SIDE_EFFECT_FAMILIES <= present):
            raise EffectsErrorsCoverageError(
                "side-effect families incomplete: missing "
                + ", ".join(sorted(REQUIRED_SIDE_EFFECT_FAMILIES - present))
            )
        if not (REQUIRED_ERROR_RETRY_FAMILIES <= present):
            raise EffectsErrorsCoverageError(
                "error/retry families incomplete: missing "
                + ", ".join(sorted(REQUIRED_ERROR_RETRY_FAMILIES - present))
            )


def build_effects_errors_operators(
    specs: Iterable[EffectsErrorsOperatorSpec] | None = None,
    *,
    producer_id: str = EFFECTS_ERRORS_OPERATORS_PRODUCER,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> EffectsErrorsMutationOperators:
    """Build a sealed catalogue from specs (defaults: normative full set).

    The sealed ``SideEffectErrorRetryMutationOperators@1`` interface always
    requires complete family and class coverage; incomplete assemblies fail
    closed.
    """

    recipe_list = (
        list(effects_errors_operator_specs()) if specs is None else list(specs)
    )
    if not recipe_list:
        raise EffectsErrorsError(
            "side-effect/error-retry catalogue requires at least one operator spec"
        )
    handles: list[EffectsErrorsOperator] = []
    for spec in recipe_list:
        if not isinstance(spec, EffectsErrorsOperatorSpec):
            raise EffectsErrorsError(
                "specs entries must be EffectsErrorsOperatorSpec"
            )
        definition = build_effects_errors_operator(spec)
        handles.append(
            EffectsErrorsOperator(
                _definition=definition,
                family=spec.family,
                spec_operator_id=spec.operator_id,
            )
        )
    catalogue = EffectsErrorsMutationOperators(
        operators=handles,
        producer_id=producer_id,
        notes=notes
        if notes is not None
        else (
            "Normative side-effect and error/retry mutation operators with "
            "semantic intent and equivalence hints (AAE-017)"
        ),
        metadata=metadata or {"task_id": "AAE-017"},
    )
    catalogue.assert_complete_coverage()
    return catalogue


def default_effects_errors_operators() -> EffectsErrorsMutationOperators:
    """Return the normative sealed catalogue (stable identity across calls)."""

    return build_effects_errors_operators()


def effects_errors_operator_definitions() -> tuple[MutationOperatorDefinition, ...]:
    """Convenience: sealed definitions only, deterministic order."""

    return default_effects_errors_operators().definitions()


def effects_errors_families_covered() -> frozenset[str]:
    """Return the family set covered by the normative catalogue."""

    return frozenset(default_effects_errors_operators().families())


# Alias matching the interface name used in task metadata.
SideEffectErrorRetryMutationOperators = EffectsErrorsMutationOperators


__all__ = [
    "ADMITTED_OPERATOR_CLASSES",
    "DEFAULT_ERROR_RETRY_RISK_CLASS",
    "DEFAULT_SIDE_EFFECT_RISK_CLASS",
    "EFFECTS_ERRORS_OPERATORS_INTERFACE",
    "EFFECTS_ERRORS_OPERATORS_PRODUCER",
    "EFFECTS_ERRORS_OPERATORS_SCHEMA",
    "EFFECTS_ERRORS_OPERATORS_VERSION",
    "EFFECTS_ERRORS_OPERATOR_VERSION",
    "EffectsErrorsCoverageError",
    "EffectsErrorsError",
    "EffectsErrorsFamily",
    "EffectsErrorsMutationOperators",
    "EffectsErrorsOperator",
    "EffectsErrorsOperatorSpec",
    "REQUIRED_EFFECTS_ERRORS_FAMILIES",
    "REQUIRED_ERROR_RETRY_FAMILIES",
    "REQUIRED_SIDE_EFFECT_FAMILIES",
    "SideEffectErrorRetryMutationOperators",
    "assert_effects_errors_operator_defaults",
    "build_effects_errors_operator",
    "build_effects_errors_operators",
    "default_effects_errors_operators",
    "effects_errors_families_covered",
    "effects_errors_operator_definitions",
    "effects_errors_operator_specs",
]
