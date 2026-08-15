"""Control-flow mutation operators (AAE-015).

Interface: ``ControlFlowMutationOperators@1``

Sealed, bounded, deterministic operator catalogue for the ``control_flow``
operator class. Coverage is normative and complete for the plan's control-flow
family:

* conditional inversion
* branch removal / unconditional behavior
* comparison boundary shifts
* recovery / obligation early return
* loop termination changes
* cancellation path changes

Every operator carries a nonempty semantic intent and equivalence hints
(``likely_equivalent_conditions``). Operators never open a store, mutate
production worktrees, or grant assurance authority.

Generation callables that rewrite source live in AAE-022; this module owns
canonical declarations, family coverage, and registry admission for the class.
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

CONTROL_FLOW_OPERATORS_INTERFACE: Final[str] = "ControlFlowMutationOperators@1"
CONTROL_FLOW_OPERATORS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-"
    "control-flow-mutation-operators@1"
)
CONTROL_FLOW_OPERATORS_VERSION: Final[str] = "1"
CONTROL_FLOW_OPERATORS_PRODUCER: Final[str] = (
    "adversarial-assurance.control-flow-mutation-operators@1"
)
CONTROL_FLOW_OPERATOR_VERSION: Final[str] = "1"

# Tight default scope for local control-structure rewrites.
_DEFAULT_MAX_FILES: Final[int] = 1
_DEFAULT_MAX_SYMBOLS: Final[int] = 2
_DEFAULT_MAX_SPAN_LINES: Final[int] = 64
_DEFAULT_MAX_MUTANTS_PER_TARGET: Final[int] = 6

DEFAULT_CONTROL_FLOW_RISK_CLASS: Final[str] = MutationRiskClass.CRITICAL_INVARIANT.value

_DEFAULT_LANGUAGES: Final[tuple[str, ...]] = ("python", "typescript")
_DEFAULT_ARTIFACT_TYPES: Final[tuple[str, ...]] = ("source_module",)
_DEFAULT_PREREQUISITES: Final[tuple[str, ...]] = (
    "parsed_ast",
    "symbol_table",
)

# Metadata key for family binding (avoid private-field markers).
_FAMILY_METADATA_KEY: Final[str] = "cf_family"


class ControlFlowError(AssuranceBaseError):
    """Raised when a control-flow operator contract fails closed."""


class ControlFlowCoverageError(ControlFlowError):
    """Raised when the catalogue does not cover a required family."""


class ControlFlowFamily(str, Enum):
    """Closed family keys required by plan acceptance for AAE-015."""

    INVERSION = "inversion"
    BRANCH_REMOVAL = "branch_removal"
    BOUNDARY_SHIFT = "boundary_shift"
    RECOVERY_OBLIGATION_EARLY_RETURN = "recovery_obligation_early_return"
    LOOP_TERMINATION = "loop_termination"
    CANCELLATION = "cancellation"


REQUIRED_CONTROL_FLOW_FAMILIES: Final[frozenset[str]] = frozenset(
    item.value for item in ControlFlowFamily
)


# ---------------------------------------------------------------------------
# Spec / recipe types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ControlFlowOperatorSpec:
    """Declarative recipe for one sealed control-flow operator.

    Specs are pure data used to construct ``MutationOperatorDefinition``
    values. They are not durable CAS records.
    """

    operator_id: str
    family: ControlFlowFamily | str
    semantic_intent: str
    syntactic_transformation: str
    expected_violated_property_classes: Sequence[PropertyClass | str]
    likely_equivalent_conditions: Sequence[str] = ()
    risk_class: MutationRiskClass | str = DEFAULT_CONTROL_FLOW_RISK_CLASS
    max_mutants_per_target: int = _DEFAULT_MAX_MUTANTS_PER_TARGET
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.operator_id) is not str or not self.operator_id.strip():
            raise ControlFlowError("operator_id must be a nonempty string")
        family = self.family
        if isinstance(family, ControlFlowFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = ControlFlowFamily(family).value
            except ValueError as exc:
                raise ControlFlowError(
                    f"unsupported control-flow family: {family!r}"
                ) from exc
        else:
            raise ControlFlowError("family must be ControlFlowFamily or str")
        object.__setattr__(self, "family", family_value)

        risk = self.risk_class
        if isinstance(risk, MutationRiskClass):
            risk_value = risk.value
        elif type(risk) is str:
            try:
                risk_value = MutationRiskClass(risk).value
            except ValueError as exc:
                raise ControlFlowError(f"unsupported risk_class: {risk!r}") from exc
        else:
            raise ControlFlowError("risk_class must be MutationRiskClass or str")
        object.__setattr__(self, "risk_class", risk_value)

        if type(self.semantic_intent) is not str or not self.semantic_intent.strip():
            raise ControlFlowError("semantic_intent must be nonempty")
        if (
            type(self.syntactic_transformation) is not str
            or not self.syntactic_transformation.strip()
        ):
            raise ControlFlowError("syntactic_transformation must be nonempty")

        props = tuple(self.expected_violated_property_classes)
        if not props:
            raise ControlFlowError(
                "expected_violated_property_classes must not be empty"
            )
        object.__setattr__(self, "expected_violated_property_classes", props)

        equiv = tuple(self.likely_equivalent_conditions or ())
        if not equiv:
            raise ControlFlowError(
                "likely_equivalent_conditions must provide equivalence hints"
            )
        for condition in equiv:
            if type(condition) is not str or not condition.strip():
                raise ControlFlowError(
                    "likely_equivalent_conditions entries must be nonempty strings"
                )
        object.__setattr__(self, "likely_equivalent_conditions", equiv)

        if (
            type(self.max_mutants_per_target) is not int
            or isinstance(self.max_mutants_per_target, bool)
            or self.max_mutants_per_target < 1
        ):
            raise ControlFlowError("max_mutants_per_target must be a positive integer")

        meta = dict(self.metadata or {})
        meta.setdefault(_FAMILY_METADATA_KEY, family_value)
        try:
            reject_private_model_authority_and_host_fallbacks(
                meta, path="ControlFlowOperatorSpec.metadata"
            )
            cid_for_structured(meta)
        except Exception as exc:  # noqa: BLE001
            raise ControlFlowError(
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


def assert_control_flow_operator_defaults(
    operator: MutationOperatorDefinition,
) -> None:
    """Fail closed when a control-flow operator lacks class or property defaults."""

    if not isinstance(operator, MutationOperatorDefinition):
        raise ControlFlowError(
            "operator must be a sealed MutationOperatorDefinition"
        )
    if operator.operator_class != OperatorClass.CONTROL_FLOW.value:
        raise ControlFlowError(
            "operator_class must be control_flow for control-flow defaults"
        )
    if not operator.semantic_intent or not str(operator.semantic_intent).strip():
        raise ControlFlowError(
            f"operator {operator.operator_id} must declare semantic_intent"
        )
    if not operator.likely_equivalent_conditions:
        raise ControlFlowError(
            f"operator {operator.operator_id} must declare equivalence hints "
            "(likely_equivalent_conditions)"
        )
    props = set(operator.expected_violated_property_classes)
    allowed = {
        PropertyClass.CONTROL_INVARIANT.value,
        PropertyClass.SIDE_EFFECT_OBLIGATION.value,
        PropertyClass.ERROR_HANDLING.value,
        PropertyClass.CANCELLATION.value,
        PropertyClass.STATE_TRANSITION.value,
        PropertyClass.COMPENSATION.value,
    }
    if not (props & allowed):
        raise ControlFlowError(
            f"operator {operator.operator_id} must expect a control-flow-related "
            "property violation "
            f"(one of {sorted(allowed)})"
        )


def build_control_flow_operator(
    spec: ControlFlowOperatorSpec,
    *,
    supported_languages: Sequence[str] | None = None,
    supported_artifact_types: Sequence[str] | None = None,
    target_prerequisites: Sequence[str] | None = None,
    scope_limits: ScopeLimits | None = None,
    rollback: RollbackDeclaration | None = None,
    required_sandbox: SandboxRequirement | None = None,
    operator_version: str = CONTROL_FLOW_OPERATOR_VERSION,
) -> MutationOperatorDefinition:
    """Seal one control-flow operator under bounded deterministic defaults."""

    if not isinstance(spec, ControlFlowOperatorSpec):
        raise ControlFlowError("spec must be a ControlFlowOperatorSpec")
    definition = MutationOperatorDefinition(
        operator_id=spec.operator_id,
        operator_version=operator_version,
        operator_class=OperatorClass.CONTROL_FLOW,
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
        raise ControlFlowError(str(exc)) from exc
    assert_control_flow_operator_defaults(sealed)
    return sealed


# ---------------------------------------------------------------------------
# Normative catalogue recipes (plan acceptance families)
# ---------------------------------------------------------------------------


def control_flow_operator_specs() -> tuple[ControlFlowOperatorSpec, ...]:
    """Return the closed, ordered set of normative operator recipes."""

    control = PropertyClass.CONTROL_INVARIANT
    obligation = PropertyClass.SIDE_EFFECT_OBLIGATION
    error_handling = PropertyClass.ERROR_HANDLING
    cancellation = PropertyClass.CANCELLATION
    compensation = PropertyClass.COMPENSATION

    return (
        # --- inversion -------------------------------------------------------
        ControlFlowOperatorSpec(
            operator_id="cf_invert_conditional",
            family=ControlFlowFamily.INVERSION,
            semantic_intent=(
                "Invert a boolean guard so the then-branch runs when the "
                "original condition is false and the else-branch runs when "
                "the original condition is true"
            ),
            syntactic_transformation="negate_conditional_predicate",
            expected_violated_property_classes=(control,),
            likely_equivalent_conditions=(
                "predicate_is_tautology_or_contradiction",
                "then_and_else_bodies_are_observationally_identical",
                "guard_is_dead_code_under_dominating_path_condition",
            ),
            risk_class=MutationRiskClass.CRITICAL_INVARIANT,
            notes="Conditional inversion of if/elif/ternary guards",
        ),
        ControlFlowOperatorSpec(
            operator_id="cf_invert_loop_guard",
            family=ControlFlowFamily.INVERSION,
            semantic_intent=(
                "Invert a loop continuation predicate so the loop iterates "
                "when it should stop and stops when it should continue"
            ),
            syntactic_transformation="negate_loop_condition",
            expected_violated_property_classes=(control,),
            likely_equivalent_conditions=(
                "loop_body_is_empty_or_pure_no_side_effects",
                "loop_is_statically_unreached",
                "condition_is_constant_under_context",
            ),
            risk_class=MutationRiskClass.CRITICAL_INVARIANT,
            notes="Loop-guard inversion (while/for filters)",
        ),
        # --- branch removal / unconditional behavior -------------------------
        ControlFlowOperatorSpec(
            operator_id="cf_remove_then_branch",
            family=ControlFlowFamily.BRANCH_REMOVAL,
            semantic_intent=(
                "Remove the then-branch of a conditional so the guarded body "
                "never executes even when the condition holds"
            ),
            syntactic_transformation="replace_then_body_with_pass_or_empty_block",
            expected_violated_property_classes=(control,),
            likely_equivalent_conditions=(
                "then_body_is_already_empty",
                "condition_is_statically_false",
                "then_body_effects_are_unreachable_or_dead",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Branch removal: drop then-body",
        ),
        ControlFlowOperatorSpec(
            operator_id="cf_force_then_unconditional",
            family=ControlFlowFamily.BRANCH_REMOVAL,
            semantic_intent=(
                "Force unconditional execution of the then-branch by replacing "
                "the guard with a constant true (or dropping the condition)"
            ),
            syntactic_transformation="replace_condition_with_true_or_drop_guard",
            expected_violated_property_classes=(control,),
            likely_equivalent_conditions=(
                "condition_is_statically_true",
                "else_branch_absent_and_then_body_always_required",
                "guard_is_redundant_under_dominators",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Unconditional then-behavior",
        ),
        ControlFlowOperatorSpec(
            operator_id="cf_remove_else_branch",
            family=ControlFlowFamily.BRANCH_REMOVAL,
            semantic_intent=(
                "Remove the else-branch so failure/default handling is skipped "
                "when the condition is false"
            ),
            syntactic_transformation="drop_else_clause",
            expected_violated_property_classes=(control, error_handling),
            likely_equivalent_conditions=(
                "else_body_is_already_empty",
                "condition_is_statically_true",
                "else_effects_are_pure_or_observationally_void",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Branch removal: drop else-body",
        ),
        # --- boundary shifts -------------------------------------------------
        ControlFlowOperatorSpec(
            operator_id="cf_boundary_lt_to_le",
            family=ControlFlowFamily.BOUNDARY_SHIFT,
            semantic_intent=(
                "Shift a strict less-than comparison boundary to less-or-equal, "
                "admitting the equality case that the original guard excluded"
            ),
            syntactic_transformation="replace_lt_with_le",
            expected_violated_property_classes=(control,),
            likely_equivalent_conditions=(
                "equality_case_is_impossible_by_type_or_domain",
                "boundary_value_is_never_produced",
                "adjacent_guards_already_cover_equality",
            ),
            risk_class=MutationRiskClass.CRITICAL_INVARIANT,
            notes="Off-by-one: < becomes <=",
        ),
        ControlFlowOperatorSpec(
            operator_id="cf_boundary_le_to_lt",
            family=ControlFlowFamily.BOUNDARY_SHIFT,
            semantic_intent=(
                "Shift a less-or-equal comparison boundary to strict less-than, "
                "excluding the equality case the original guard admitted"
            ),
            syntactic_transformation="replace_le_with_lt",
            expected_violated_property_classes=(control,),
            likely_equivalent_conditions=(
                "equality_case_is_impossible_by_type_or_domain",
                "boundary_value_is_never_produced",
                "exclusive_bound_is_already_enforced_elsewhere",
            ),
            risk_class=MutationRiskClass.CRITICAL_INVARIANT,
            notes="Off-by-one: <= becomes <",
        ),
        ControlFlowOperatorSpec(
            operator_id="cf_boundary_gt_to_ge",
            family=ControlFlowFamily.BOUNDARY_SHIFT,
            semantic_intent=(
                "Shift a strict greater-than comparison boundary to "
                "greater-or-equal, admitting the equality case"
            ),
            syntactic_transformation="replace_gt_with_ge",
            expected_violated_property_classes=(control,),
            likely_equivalent_conditions=(
                "equality_case_is_impossible_by_type_or_domain",
                "boundary_value_is_never_produced",
            ),
            risk_class=MutationRiskClass.CRITICAL_INVARIANT,
            notes="Off-by-one: > becomes >=",
        ),
        ControlFlowOperatorSpec(
            operator_id="cf_boundary_ge_to_gt",
            family=ControlFlowFamily.BOUNDARY_SHIFT,
            semantic_intent=(
                "Shift a greater-or-equal comparison boundary to strict "
                "greater-than, excluding the equality case"
            ),
            syntactic_transformation="replace_ge_with_gt",
            expected_violated_property_classes=(control,),
            likely_equivalent_conditions=(
                "equality_case_is_impossible_by_type_or_domain",
                "boundary_value_is_never_produced",
            ),
            risk_class=MutationRiskClass.CRITICAL_INVARIANT,
            notes="Off-by-one: >= becomes >",
        ),
        # --- recovery / obligation early return ------------------------------
        ControlFlowOperatorSpec(
            operator_id="cf_early_return_before_recovery",
            family=ControlFlowFamily.RECOVERY_OBLIGATION_EARLY_RETURN,
            semantic_intent=(
                "Insert or promote an early return that exits before recovery "
                "or cleanup runs after a partial failure"
            ),
            syntactic_transformation="insert_early_return_before_recovery_block",
            expected_violated_property_classes=(control, obligation, error_handling),
            likely_equivalent_conditions=(
                "recovery_block_is_already_unreachable",
                "recovery_is_idempotent_no_op_for_all_paths",
                "failure_mode_never_occurs_under_context",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Skip recovery via early return",
        ),
        ControlFlowOperatorSpec(
            operator_id="cf_early_return_before_obligation",
            family=ControlFlowFamily.RECOVERY_OBLIGATION_EARLY_RETURN,
            semantic_intent=(
                "Return early before a postcondition obligation (write-back, "
                "ack, audit, or commit) so success is reported without the "
                "required side effect"
            ),
            syntactic_transformation="insert_early_return_before_obligation",
            expected_violated_property_classes=(control, obligation),
            likely_equivalent_conditions=(
                "obligation_already_satisfied_on_all_paths",
                "obligation_is_optional_by_contract",
                "caller_does_not_observe_obligation_effects",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Skip obligation via early return",
        ),
        # --- loop termination ------------------------------------------------
        ControlFlowOperatorSpec(
            operator_id="cf_loop_break_early",
            family=ControlFlowFamily.LOOP_TERMINATION,
            semantic_intent=(
                "Insert an unconditional or over-broad break so the loop "
                "terminates before remaining iterations that the program "
                "requires"
            ),
            syntactic_transformation="insert_early_break_in_loop_body",
            expected_violated_property_classes=(control,),
            likely_equivalent_conditions=(
                "loop_iterates_at_most_once_already",
                "remaining_iterations_have_no_observable_effect",
                "loop_is_statically_unreached",
            ),
            risk_class=MutationRiskClass.CRITICAL_INVARIANT,
            notes="Premature loop termination",
        ),
        ControlFlowOperatorSpec(
            operator_id="cf_loop_skip_termination_check",
            family=ControlFlowFamily.LOOP_TERMINATION,
            semantic_intent=(
                "Remove or weaken a break/return/limit check so the loop may "
                "continue past its intended termination bound"
            ),
            syntactic_transformation="remove_or_weaken_loop_break_or_limit",
            expected_violated_property_classes=(control,),
            likely_equivalent_conditions=(
                "outer_bound_already_enforces_same_limit",
                "collection_size_never_exceeds_removed_bound",
                "loop_body_is_pure_and_idempotent",
            ),
            risk_class=MutationRiskClass.CRITICAL_INVARIANT,
            notes="Missed loop termination / over-iteration",
        ),
        # --- cancellation ----------------------------------------------------
        ControlFlowOperatorSpec(
            operator_id="cf_ignore_cancellation",
            family=ControlFlowFamily.CANCELLATION,
            semantic_intent=(
                "Ignore a cooperative cancellation signal so work continues "
                "after the caller requested stop"
            ),
            syntactic_transformation="replace_cancellation_check_with_false_or_omit",
            expected_violated_property_classes=(control, cancellation),
            likely_equivalent_conditions=(
                "cancellation_never_signalled_in_campaign_scope",
                "operation_is_already_atomic_and_uninterruptible_by_contract",
                "cancellation_check_is_redundant_with_harder_timeout",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Skip cancellation checks",
        ),
        ControlFlowOperatorSpec(
            operator_id="cf_cancel_without_cleanup",
            family=ControlFlowFamily.CANCELLATION,
            semantic_intent=(
                "Take the cancellation exit path without running required "
                "cleanup, compensation, or resource-release steps"
            ),
            syntactic_transformation="return_on_cancel_before_cleanup",
            expected_violated_property_classes=(
                control,
                cancellation,
                compensation,
                obligation,
            ),
            likely_equivalent_conditions=(
                "no_resources_acquired_before_cancel_point",
                "cleanup_is_handled_by_scope_exit_guarantees",
                "compensation_is_optional_on_cancel_by_contract",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Cancel without cleanup/compensation",
        ),
    )


# ---------------------------------------------------------------------------
# Operator handles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ControlFlowOperator(MutationOperator):
    """Declaration-backed control-flow operator with family binding.

    Interface membership: ``ControlFlowMutationOperators@1`` catalogue entry.
    Does not generate source rewrites; generation is owned by AAE-022.
    """

    _definition: MutationOperatorDefinition
    family: str
    spec_operator_id: str

    def __post_init__(self) -> None:
        sealed = canonicalize_operator_declaration(self._definition)
        assert_control_flow_operator_defaults(sealed)
        if sealed.operator_class != OperatorClass.CONTROL_FLOW.value:
            raise ControlFlowError(
                "ControlFlowOperator requires operator_class control_flow"
            )
        try:
            family_value = ControlFlowFamily(self.family).value
        except ValueError as exc:
            raise ControlFlowError(
                f"unsupported control-flow family: {self.family!r}"
            ) from exc
        meta_family = sealed.metadata.get(_FAMILY_METADATA_KEY)
        if meta_family is not None and meta_family != family_value:
            raise ControlFlowError(
                "definition metadata cf_family does not match family binding "
                f"({meta_family!r} != {family_value!r})"
            )
        object.__setattr__(self, "_definition", sealed)
        object.__setattr__(self, "family", family_value)
        if type(self.spec_operator_id) is not str or not self.spec_operator_id:
            raise ControlFlowError("spec_operator_id must be nonempty")
        if self.spec_operator_id != sealed.operator_id:
            raise ControlFlowError(
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
        raise ControlFlowError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise ControlFlowError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    return dict(data)


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ControlFlowError(f"{name} must be a nonempty trimmed string")
    return value


@dataclass(frozen=True, slots=True)
class ControlFlowMutationOperators:
    """Immutable catalogue of sealed control-flow mutation operators.

    Interface: ``ControlFlowMutationOperators@1``
    """

    operators: Sequence[ControlFlowOperator]
    producer_id: str = CONTROL_FLOW_OPERATORS_PRODUCER
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
            raise ControlFlowError(
                "operators must be a sequence of ControlFlowOperator"
            )
        sealed: list[ControlFlowOperator] = []
        seen_ids: set[str] = set()
        seen_cids: set[str] = set()
        families: set[str] = set()
        for item in self.operators:
            if not isinstance(item, ControlFlowOperator):
                raise ControlFlowError(
                    "operators entries must be ControlFlowOperator"
                )
            definition = item.definition
            assert_control_flow_operator_defaults(definition)
            try:
                assert_operator_bounded(definition)
            except OperatorBoundError as exc:
                raise ControlFlowError(str(exc)) from exc
            if definition.operator_id in seen_ids:
                raise ControlFlowError(
                    f"duplicate operator_id in catalogue: {definition.operator_id}"
                )
            if definition.operator_cid in seen_cids:
                raise ControlFlowError(
                    f"duplicate operator_cid in catalogue: {definition.operator_cid}"
                )
            seen_ids.add(definition.operator_id)
            seen_cids.add(definition.operator_cid)
            families.add(item.family)
            sealed.append(item)

        missing = REQUIRED_CONTROL_FLOW_FAMILIES - families
        if missing:
            raise ControlFlowCoverageError(
                "control-flow catalogue missing required families: "
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
                meta_payload, path="ControlFlowMutationOperators.metadata"
            )
            cid_for_structured(meta_payload)
        except Exception as exc:  # noqa: BLE001
            raise ControlFlowError(
                "metadata must be DAG-JSON structured data without model authority"
            ) from exc
        object.__setattr__(self, "metadata", MappingProxyType(meta_payload))

        computed = cid_for_structured(self._identity_payload_without_catalogue_id())
        if self.catalogue_id is None:
            object.__setattr__(self, "catalogue_id", computed)
        else:
            claimed = _text(self.catalogue_id, "catalogue_id")
            if claimed != computed:
                raise ControlFlowError(
                    "catalogue_id identity mismatch with recomputed catalogue identity"
                )
            object.__setattr__(self, "catalogue_id", claimed)

    def _identity_payload_without_catalogue_id(self) -> dict[str, Any]:
        return {
            "schema": CONTROL_FLOW_OPERATORS_SCHEMA,
            "interface_id": CONTROL_FLOW_OPERATORS_INTERFACE,
            "catalogue_version": CONTROL_FLOW_OPERATORS_VERSION,
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
            "schema": CONTROL_FLOW_OPERATORS_SCHEMA,
            "interface_id": CONTROL_FLOW_OPERATORS_INTERFACE,
            "catalogue_version": CONTROL_FLOW_OPERATORS_VERSION,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "ControlFlowMutationOperators":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != CONTROL_FLOW_OPERATORS_SCHEMA:
            raise ControlFlowError(
                "unsupported ControlFlowMutationOperators schema version"
            )
        if payload.pop("interface_id") != CONTROL_FLOW_OPERATORS_INTERFACE:
            raise ControlFlowError(
                "unsupported ControlFlowMutationOperators interface_id"
            )
        version = payload.pop(
            "catalogue_version", CONTROL_FLOW_OPERATORS_VERSION
        )
        if version != CONTROL_FLOW_OPERATORS_VERSION:
            raise ControlFlowError(
                "unsupported ControlFlowMutationOperators catalogue_version"
            )
        payload.pop("operator_cids", None)
        payload.pop("operator_count", None)
        payload.pop("families", None)
        raw_ops = payload["operators"]
        if not isinstance(raw_ops, list):
            raise ControlFlowError("operators must be a list")
        operators: list[ControlFlowOperator] = []
        for entry in raw_ops:
            if not isinstance(entry, Mapping):
                raise ControlFlowError(
                    "operators entries must be mappings with family and definition"
                )
            definition_raw = entry.get("definition")
            if isinstance(definition_raw, MutationOperatorDefinition):
                definition = definition_raw
            elif isinstance(definition_raw, Mapping):
                definition = MutationOperatorDefinition.from_dict(definition_raw)
            else:
                raise ControlFlowError(
                    "operators[].definition must be MutationOperatorDefinition or mapping"
                )
            family = entry.get("family")
            if family is None:
                family = definition.metadata.get(_FAMILY_METADATA_KEY)
            spec_id = entry.get("spec_operator_id", definition.operator_id)
            operators.append(
                ControlFlowOperator(
                    _definition=definition,
                    family=family,
                    spec_operator_id=spec_id,
                )
            )
        return cls(
            operators=operators,
            producer_id=payload.get(
                "producer_id", CONTROL_FLOW_OPERATORS_PRODUCER
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
        if isinstance(item, ControlFlowOperator):
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

    def list_operators(self) -> tuple[ControlFlowOperator, ...]:
        return tuple(self.operators)

    def operators_for_family(
        self, family: ControlFlowFamily | str
    ) -> tuple[ControlFlowOperator, ...]:
        if isinstance(family, ControlFlowFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = ControlFlowFamily(family).value
            except ValueError as exc:
                raise ControlFlowError(
                    f"unsupported control-flow family: {family!r}"
                ) from exc
        else:
            raise ControlFlowError("family must be ControlFlowFamily or str")
        return tuple(item for item in self.operators if item.family == family_value)

    def get(
        self,
        operator_id: str,
        operator_version: str | None = None,
    ) -> ControlFlowOperator:
        operator_id = _text(operator_id, "operator_id")
        matches = [
            item for item in self.operators if item.operator_id == operator_id
        ]
        if not matches:
            raise ControlFlowError(f"unknown operator_id: {operator_id}")
        if operator_version is None:
            if len(matches) != 1:
                versions = ", ".join(sorted({item.operator_version for item in matches}))
                raise ControlFlowError(
                    f"operator_id {operator_id} is ambiguous across versions "
                    f"({versions}); provide operator_version"
                )
            return matches[0]
        operator_version = _text(operator_version, "operator_version")
        for item in matches:
            if item.operator_version == operator_version:
                return item
        raise ControlFlowError(
            f"unknown operator: {operator_id}@{operator_version}"
        )

    def get_by_cid(self, operator_cid: str) -> ControlFlowOperator:
        operator_cid = _text(operator_cid, "operator_cid")
        for item in self.operators:
            if item.operator_cid == operator_cid:
                return item
        raise ControlFlowError(f"unknown operator_cid: {operator_cid}")

    def operators_for_target(
        self, target: MutationTarget
    ) -> tuple[ControlFlowOperator, ...]:
        if not isinstance(target, MutationTarget):
            raise ControlFlowError("target must be a MutationTarget")
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
                producer_id=producer_id or CONTROL_FLOW_OPERATORS_PRODUCER,
                notes=notes if notes is not None else self.notes,
                metadata=metadata if metadata is not None else dict(self.metadata),
            )
        except OperatorRegistryError as exc:
            raise ControlFlowError(str(exc)) from exc

    def register_into(
        self, builder: MutationOperatorRegistryBuilder
    ) -> tuple[MutationOperatorDefinition, ...]:
        """Admit every catalogue operator into a mutable registry builder."""

        if not isinstance(builder, MutationOperatorRegistryBuilder):
            raise ControlFlowError(
                "builder must be a MutationOperatorRegistryBuilder"
            )
        sealed: list[MutationOperatorDefinition] = []
        for item in self.operators:
            try:
                sealed.append(builder.register(item.definition))
            except OperatorRegistryError as exc:
                raise ControlFlowError(str(exc)) from exc
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
        missing = REQUIRED_CONTROL_FLOW_FAMILIES - present
        if missing:
            raise ControlFlowCoverageError(
                "control-flow catalogue missing required families: "
                + ", ".join(sorted(missing))
            )


def build_control_flow_operators(
    specs: Iterable[ControlFlowOperatorSpec] | None = None,
    *,
    producer_id: str = CONTROL_FLOW_OPERATORS_PRODUCER,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ControlFlowMutationOperators:
    """Build a sealed catalogue from specs (defaults: normative full set).

    The sealed ``ControlFlowMutationOperators@1`` interface always requires
    complete family coverage; incomplete assemblies fail closed.
    """

    recipe_list = (
        list(control_flow_operator_specs()) if specs is None else list(specs)
    )
    if not recipe_list:
        raise ControlFlowError(
            "control-flow catalogue requires at least one operator spec"
        )
    handles: list[ControlFlowOperator] = []
    for spec in recipe_list:
        if not isinstance(spec, ControlFlowOperatorSpec):
            raise ControlFlowError(
                "specs entries must be ControlFlowOperatorSpec"
            )
        definition = build_control_flow_operator(spec)
        handles.append(
            ControlFlowOperator(
                _definition=definition,
                family=spec.family,
                spec_operator_id=spec.operator_id,
            )
        )
    catalogue = ControlFlowMutationOperators(
        operators=handles,
        producer_id=producer_id,
        notes=notes
        if notes is not None
        else (
            "Normative control-flow mutation operators with semantic intent "
            "and equivalence hints (AAE-015)"
        ),
        metadata=metadata or {"task_id": "AAE-015"},
    )
    catalogue.assert_complete_coverage()
    return catalogue


def default_control_flow_operators() -> ControlFlowMutationOperators:
    """Return the normative sealed catalogue (stable identity across calls)."""

    return build_control_flow_operators()


def control_flow_operator_definitions() -> tuple[MutationOperatorDefinition, ...]:
    """Convenience: sealed definitions only, deterministic order."""

    return default_control_flow_operators().definitions()


def control_flow_families_covered() -> frozenset[str]:
    """Return the family set covered by the normative catalogue."""

    return frozenset(default_control_flow_operators().families())


__all__ = [
    "CONTROL_FLOW_OPERATORS_INTERFACE",
    "CONTROL_FLOW_OPERATORS_PRODUCER",
    "CONTROL_FLOW_OPERATORS_SCHEMA",
    "CONTROL_FLOW_OPERATORS_VERSION",
    "CONTROL_FLOW_OPERATOR_VERSION",
    "ControlFlowCoverageError",
    "ControlFlowError",
    "ControlFlowFamily",
    "ControlFlowMutationOperators",
    "ControlFlowOperator",
    "ControlFlowOperatorSpec",
    "DEFAULT_CONTROL_FLOW_RISK_CLASS",
    "REQUIRED_CONTROL_FLOW_FAMILIES",
    "assert_control_flow_operator_defaults",
    "build_control_flow_operator",
    "build_control_flow_operators",
    "control_flow_families_covered",
    "control_flow_operator_definitions",
    "control_flow_operator_specs",
    "default_control_flow_operators",
]
