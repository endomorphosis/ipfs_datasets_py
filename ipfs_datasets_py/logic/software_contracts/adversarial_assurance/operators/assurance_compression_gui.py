"""Test, proof, semantic-compression, and conditional GUI operators (AAE-020).

Interface: ``AssuranceCompressionGuiMutationOperators@1``

Sealed, bounded, deterministic operator catalogue covering three plan classes:

* ``test_proof`` — weak/deleted/skipped tests, fixtures, and
  vacuous/stale/incomplete proofs
* ``semantic_compression`` — capsule, dependency, and context omissions
* ``gui_action_binding`` — only canonical GUI action bindings
  (dispatchability, confirmation, handler, stale policy, recovery, early
  success, critical keyboard accessibility)

Broad visual mutation is explicitly absent and rejected. Operators never open
a store, mutate production worktrees, or grant assurance authority.

Generation callables that rewrite source live in AAE-022; this module owns
canonical declarations, family coverage, and registry admission for the
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

ASSURANCE_COMPRESSION_GUI_OPERATORS_INTERFACE: Final[str] = (
    "AssuranceCompressionGuiMutationOperators@1"
)
ASSURANCE_COMPRESSION_GUI_OPERATORS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-"
    "assurance-compression-gui-mutation-operators@1"
)
ASSURANCE_COMPRESSION_GUI_OPERATORS_VERSION: Final[str] = "1"
ASSURANCE_COMPRESSION_GUI_OPERATORS_PRODUCER: Final[str] = (
    "adversarial-assurance.assurance-compression-gui-mutation-operators@1"
)
ASSURANCE_COMPRESSION_GUI_OPERATOR_VERSION: Final[str] = "1"

_DEFAULT_MAX_FILES: Final[int] = 1
_DEFAULT_MAX_SYMBOLS: Final[int] = 2
_DEFAULT_MAX_SPAN_LINES: Final[int] = 64
_DEFAULT_MAX_MUTANTS_PER_TARGET: Final[int] = 4

DEFAULT_ASSURANCE_RISK_CLASS: Final[str] = MutationRiskClass.HIGH.value
DEFAULT_PROOF_RISK_CLASS: Final[str] = MutationRiskClass.PROOF_RECEIPT_TRUST.value

# Operator classes owned by this catalogue.
OWNED_OPERATOR_CLASSES: Final[frozenset[str]] = frozenset(
    {
        OperatorClass.TEST_PROOF.value,
        OperatorClass.SEMANTIC_COMPRESSION.value,
        OperatorClass.GUI_ACTION_BINDING.value,
    }
)

# Tokens that mark broad visual mutation (forbidden for this catalogue).
FORBIDDEN_VISUAL_MUTATION_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "visual",
        "visual_mutation",
        "layout",
        "css",
        "stylesheet",
        "color",
        "colour",
        "pixel",
        "pixels",
        "rendering",
        "render_style",
        "theme",
        "typography",
        "font",
        "margin",
        "padding",
        "spacing",
        "animation",
        "opacity",
        "border_radius",
        "shadow",
        "icon_swap",
        "screenshot",
        "cosmetic",
    }
)

_DEFAULT_LANGUAGES: Final[tuple[str, ...]] = ("python", "typescript")
_DEFAULT_PREREQUISITES: Final[tuple[str, ...]] = (
    "parsed_ast",
    "symbol_table",
)
_GUI_PREREQUISITES: Final[tuple[str, ...]] = (
    "parsed_ast",
    "symbol_table",
    "canonical_gui_optimizer_artifact",
)

_ARTIFACT_TYPES_BY_CLASS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        OperatorClass.TEST_PROOF.value: (
            "test_module",
            "proof_unit",
            "fixture_module",
            "source_module",
        ),
        OperatorClass.SEMANTIC_COMPRESSION.value: (
            "semantic_capsule",
            "dependency_graph",
            "selection_manifest",
            "source_module",
        ),
        OperatorClass.GUI_ACTION_BINDING.value: (
            "gui_optimizer_artifact",
            "action_binding_manifest",
            "source_module",
        ),
    }
)


class AssuranceCompressionGuiError(AssuranceBaseError):
    """Raised when an assurance/compression/GUI operator contract fails closed."""


class AssuranceCompressionGuiCoverageError(AssuranceCompressionGuiError):
    """Raised when the catalogue does not cover a required family."""


class AssuranceCompressionGuiVisualMutationError(AssuranceCompressionGuiError):
    """Raised when a broad visual mutation is admitted or requested."""


class AssuranceCompressionGuiClassError(AssuranceCompressionGuiError):
    """Raised when an operator uses an unsupported operator class."""


class AssuranceCompressionGuiFamily(str, Enum):
    """Closed family keys required by plan acceptance for AAE-020."""

    # test_proof
    WEAK_TEST = "weak_test"
    DELETED_TEST = "deleted_test"
    SKIPPED_TEST = "skipped_test"
    FIXTURE = "fixture"
    VACUOUS_PROOF = "vacuous_proof"
    STALE_PROOF = "stale_proof"
    INCOMPLETE_PROOF = "incomplete_proof"
    # semantic_compression
    CAPSULE_OMISSION = "capsule_omission"
    DEPENDENCY_OMISSION = "dependency_omission"
    CONTEXT_OMISSION = "context_omission"
    # gui_action_binding (canonical only; no broad visual)
    GUI_DISPATCHABILITY = "gui_dispatchability"
    GUI_CONFIRMATION = "gui_confirmation"
    GUI_HANDLER = "gui_handler"
    GUI_STALE_POLICY = "gui_stale_policy"
    GUI_RECOVERY = "gui_recovery"
    GUI_EARLY_SUCCESS = "gui_early_success"
    GUI_KEYBOARD_ACCESSIBILITY = "gui_keyboard_accessibility"


REQUIRED_ASSURANCE_COMPRESSION_GUI_FAMILIES: Final[frozenset[str]] = frozenset(
    item.value for item in AssuranceCompressionGuiFamily
)

_FAMILY_TO_OPERATOR_CLASS: Final[Mapping[str, str]] = MappingProxyType(
    {
        AssuranceCompressionGuiFamily.WEAK_TEST.value: OperatorClass.TEST_PROOF.value,
        AssuranceCompressionGuiFamily.DELETED_TEST.value: OperatorClass.TEST_PROOF.value,
        AssuranceCompressionGuiFamily.SKIPPED_TEST.value: OperatorClass.TEST_PROOF.value,
        AssuranceCompressionGuiFamily.FIXTURE.value: OperatorClass.TEST_PROOF.value,
        AssuranceCompressionGuiFamily.VACUOUS_PROOF.value: OperatorClass.TEST_PROOF.value,
        AssuranceCompressionGuiFamily.STALE_PROOF.value: OperatorClass.TEST_PROOF.value,
        AssuranceCompressionGuiFamily.INCOMPLETE_PROOF.value: OperatorClass.TEST_PROOF.value,
        AssuranceCompressionGuiFamily.CAPSULE_OMISSION.value: (
            OperatorClass.SEMANTIC_COMPRESSION.value
        ),
        AssuranceCompressionGuiFamily.DEPENDENCY_OMISSION.value: (
            OperatorClass.SEMANTIC_COMPRESSION.value
        ),
        AssuranceCompressionGuiFamily.CONTEXT_OMISSION.value: (
            OperatorClass.SEMANTIC_COMPRESSION.value
        ),
        AssuranceCompressionGuiFamily.GUI_DISPATCHABILITY.value: (
            OperatorClass.GUI_ACTION_BINDING.value
        ),
        AssuranceCompressionGuiFamily.GUI_CONFIRMATION.value: (
            OperatorClass.GUI_ACTION_BINDING.value
        ),
        AssuranceCompressionGuiFamily.GUI_HANDLER.value: (
            OperatorClass.GUI_ACTION_BINDING.value
        ),
        AssuranceCompressionGuiFamily.GUI_STALE_POLICY.value: (
            OperatorClass.GUI_ACTION_BINDING.value
        ),
        AssuranceCompressionGuiFamily.GUI_RECOVERY.value: (
            OperatorClass.GUI_ACTION_BINDING.value
        ),
        AssuranceCompressionGuiFamily.GUI_EARLY_SUCCESS.value: (
            OperatorClass.GUI_ACTION_BINDING.value
        ),
        AssuranceCompressionGuiFamily.GUI_KEYBOARD_ACCESSIBILITY.value: (
            OperatorClass.GUI_ACTION_BINDING.value
        ),
    }
)

_GUI_FAMILIES: Final[frozenset[str]] = frozenset(
    family
    for family, cls in _FAMILY_TO_OPERATOR_CLASS.items()
    if cls == OperatorClass.GUI_ACTION_BINDING.value
)


# ---------------------------------------------------------------------------
# Spec / recipe types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssuranceCompressionGuiOperatorSpec:
    """Declarative recipe for one sealed assurance/compression/GUI operator.

    Specs are pure data used to construct ``MutationOperatorDefinition``
    values. They are not durable CAS records.
    """

    operator_id: str
    family: AssuranceCompressionGuiFamily | str
    semantic_intent: str
    syntactic_transformation: str
    expected_violated_property_classes: Sequence[PropertyClass | str]
    operator_class: OperatorClass | str | None = None
    likely_equivalent_conditions: Sequence[str] = ()
    risk_class: MutationRiskClass | str = DEFAULT_ASSURANCE_RISK_CLASS
    max_mutants_per_target: int = _DEFAULT_MAX_MUTANTS_PER_TARGET
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.operator_id) is not str or not self.operator_id.strip():
            raise AssuranceCompressionGuiError(
                "operator_id must be a nonempty string"
            )
        family = self.family
        if isinstance(family, AssuranceCompressionGuiFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = AssuranceCompressionGuiFamily(family).value
            except ValueError as exc:
                raise AssuranceCompressionGuiError(
                    f"unsupported assurance/compression/GUI family: {family!r}"
                ) from exc
        else:
            raise AssuranceCompressionGuiError(
                "family must be AssuranceCompressionGuiFamily or str"
            )
        object.__setattr__(self, "family", family_value)

        expected_class = _FAMILY_TO_OPERATOR_CLASS[family_value]
        op_class = self.operator_class
        if op_class is None:
            op_class_value = expected_class
        elif isinstance(op_class, OperatorClass):
            op_class_value = op_class.value
        elif type(op_class) is str:
            try:
                op_class_value = OperatorClass(op_class).value
            except ValueError as exc:
                raise AssuranceCompressionGuiClassError(
                    f"unsupported operator_class: {op_class!r}"
                ) from exc
        else:
            raise AssuranceCompressionGuiError(
                "operator_class must be OperatorClass, str, or None"
            )
        if op_class_value not in OWNED_OPERATOR_CLASSES:
            raise AssuranceCompressionGuiClassError(
                f"operator_class {op_class_value!r} is not owned by "
                "AssuranceCompressionGuiMutationOperators"
            )
        if op_class_value != expected_class:
            raise AssuranceCompressionGuiClassError(
                f"family {family_value!r} requires operator_class "
                f"{expected_class!r}, got {op_class_value!r}"
            )
        object.__setattr__(self, "operator_class", op_class_value)

        risk = self.risk_class
        if isinstance(risk, MutationRiskClass):
            risk_value = risk.value
        elif type(risk) is str:
            try:
                risk_value = MutationRiskClass(risk).value
            except ValueError as exc:
                raise AssuranceCompressionGuiError(
                    f"unsupported risk_class: {risk!r}"
                ) from exc
        else:
            raise AssuranceCompressionGuiError(
                "risk_class must be MutationRiskClass or str"
            )
        object.__setattr__(self, "risk_class", risk_value)

        if type(self.semantic_intent) is not str or not self.semantic_intent.strip():
            raise AssuranceCompressionGuiError("semantic_intent must be nonempty")
        if (
            type(self.syntactic_transformation) is not str
            or not self.syntactic_transformation.strip()
        ):
            raise AssuranceCompressionGuiError(
                "syntactic_transformation must be nonempty"
            )
        _reject_visual_mutation_text(
            self.syntactic_transformation, "syntactic_transformation"
        )
        _reject_visual_mutation_text(
            self.semantic_intent,
            "semantic_intent",
            allow_exclusion_context=True,
        )
        if self.notes is not None:
            _reject_visual_mutation_text(
                self.notes, "notes", allow_exclusion_context=True
            )

        props = tuple(self.expected_violated_property_classes)
        if not props:
            raise AssuranceCompressionGuiError(
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
            raise AssuranceCompressionGuiError(
                "max_mutants_per_target must be a positive integer"
            )
        meta = dict(self.metadata or {})
        meta.setdefault("assurance_family", family_value)
        meta.setdefault("operator_class", op_class_value)
        meta.setdefault("visual_mutation_allowed", False)
        if meta.get("visual_mutation_allowed") is not False:
            raise AssuranceCompressionGuiVisualMutationError(
                "visual_mutation_allowed must be false; broad visual mutation "
                "is out of scope for AssuranceCompressionGuiMutationOperators"
            )
        try:
            reject_private_model_authority_and_host_fallbacks(
                meta, path="AssuranceCompressionGuiOperatorSpec.metadata"
            )
            cid_for_structured(meta)
        except AssuranceCompressionGuiError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AssuranceCompressionGuiError(
                "metadata must be DAG-JSON structured data without model authority"
            ) from exc
        object.__setattr__(self, "metadata", MappingProxyType(meta))


_EXCLUSION_CONTEXT_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "absent",
        "forbidden",
        "excluded",
        "disallowed",
        "out",
        "scope",
        "must_not",
        "never",
        "not",
        "no",
        "without",
        "reject",
        "rejected",
        "prohibits",
        "prohibit",
    }
)


def _reject_visual_mutation_text(
    value: str,
    name: str,
    *,
    allow_exclusion_context: bool = False,
) -> None:
    """Fail closed when text encodes broad visual mutation intent.

    When ``allow_exclusion_context`` is true (notes / catalogue prose), text
    that *mentions* visual tokens only to forbid them is permitted. Syntactic
    transformations never get this allowance.
    """

    lowered = value.lower().replace("-", "_")
    tokens = set(lowered.replace("/", " ").replace(".", " ").split())
    if allow_exclusion_context and tokens & _EXCLUSION_CONTEXT_TOKENS:
        return
    for forbidden in FORBIDDEN_VISUAL_MUTATION_TOKENS:
        if forbidden in tokens or f"_{forbidden}_" in f"_{lowered}_":
            raise AssuranceCompressionGuiVisualMutationError(
                f"{name} admits forbidden broad visual mutation token "
                f"{forbidden!r}; GUI operators cover action bindings only"
            )


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


def assert_no_broad_visual_mutation(operator: MutationOperatorDefinition) -> None:
    """Fail closed when an operator encodes broad visual mutation."""

    if not isinstance(operator, MutationOperatorDefinition):
        raise AssuranceCompressionGuiError(
            "operator must be a sealed MutationOperatorDefinition"
        )
    _reject_visual_mutation_text(
        operator.syntactic_transformation, "syntactic_transformation"
    )
    _reject_visual_mutation_text(
        operator.semantic_intent,
        "semantic_intent",
        allow_exclusion_context=True,
    )
    if operator.notes is not None:
        _reject_visual_mutation_text(
            operator.notes, "notes", allow_exclusion_context=True
        )
    if operator.metadata.get("visual_mutation_allowed") is not False:
        raise AssuranceCompressionGuiVisualMutationError(
            f"operator {operator.operator_id} must set "
            "metadata.visual_mutation_allowed=false"
        )
    if operator.operator_class == OperatorClass.GUI_ACTION_BINDING.value:
        # GUI operators must remain action-binding only.
        props = set(operator.expected_violated_property_classes)
        if PropertyClass.GUI_ACTION_BINDING.value not in props:
            raise AssuranceCompressionGuiError(
                f"GUI operator {operator.operator_id} must expect "
                "gui_action_binding property violations"
            )


def assert_assurance_compression_gui_defaults(
    operator: MutationOperatorDefinition,
) -> None:
    """Fail closed when an operator is outside this catalogue's class bounds."""

    if not isinstance(operator, MutationOperatorDefinition):
        raise AssuranceCompressionGuiError(
            "operator must be a sealed MutationOperatorDefinition"
        )
    if operator.operator_class not in OWNED_OPERATOR_CLASSES:
        raise AssuranceCompressionGuiClassError(
            f"operator_class must be one of {sorted(OWNED_OPERATOR_CLASSES)}; "
            f"got {operator.operator_class!r}"
        )
    assert_no_broad_visual_mutation(operator)

    props = set(operator.expected_violated_property_classes)
    if operator.operator_class == OperatorClass.TEST_PROOF.value:
        if not props & {
            PropertyClass.TEST_ADEQUACY.value,
            PropertyClass.PROOF_ADEQUACY.value,
            PropertyClass.RECEIPT_AUTHENTICITY.value,
        }:
            raise AssuranceCompressionGuiError(
                f"test_proof operator {operator.operator_id} must expect "
                "test_adequacy, proof_adequacy, or receipt_authenticity"
            )
    elif operator.operator_class == OperatorClass.SEMANTIC_COMPRESSION.value:
        if PropertyClass.CAPSULE_COMPLETENESS.value not in props and (
            PropertyClass.DATA_INTEGRITY.value not in props
        ):
            raise AssuranceCompressionGuiError(
                f"semantic_compression operator {operator.operator_id} must "
                "expect capsule_completeness or data_integrity violations"
            )
    elif operator.operator_class == OperatorClass.GUI_ACTION_BINDING.value:
        if PropertyClass.GUI_ACTION_BINDING.value not in props:
            raise AssuranceCompressionGuiError(
                f"gui_action_binding operator {operator.operator_id} must "
                "expect gui_action_binding property violations"
            )
        prereqs = set(operator.target_prerequisites)
        if "canonical_gui_optimizer_artifact" not in prereqs:
            raise AssuranceCompressionGuiError(
                f"GUI operator {operator.operator_id} requires prerequisite "
                "canonical_gui_optimizer_artifact"
            )


def build_assurance_compression_gui_operator(
    spec: AssuranceCompressionGuiOperatorSpec,
    *,
    supported_languages: Sequence[str] | None = None,
    supported_artifact_types: Sequence[str] | None = None,
    target_prerequisites: Sequence[str] | None = None,
    scope_limits: ScopeLimits | None = None,
    rollback: RollbackDeclaration | None = None,
    required_sandbox: SandboxRequirement | None = None,
    operator_version: str = ASSURANCE_COMPRESSION_GUI_OPERATOR_VERSION,
) -> MutationOperatorDefinition:
    """Seal one assurance/compression/GUI operator under catalogue defaults."""

    if not isinstance(spec, AssuranceCompressionGuiOperatorSpec):
        raise AssuranceCompressionGuiError(
            "spec must be an AssuranceCompressionGuiOperatorSpec"
        )
    op_class = str(spec.operator_class)
    default_artifacts = _ARTIFACT_TYPES_BY_CLASS[op_class]
    if target_prerequisites is None:
        if op_class == OperatorClass.GUI_ACTION_BINDING.value:
            prereqs: Sequence[str] = _GUI_PREREQUISITES
        else:
            prereqs = _DEFAULT_PREREQUISITES
    else:
        prereqs = target_prerequisites

    definition = MutationOperatorDefinition(
        operator_id=spec.operator_id,
        operator_version=operator_version,
        operator_class=op_class,
        supported_languages=tuple(supported_languages or _DEFAULT_LANGUAGES),
        supported_artifact_types=tuple(
            supported_artifact_types or default_artifacts
        ),
        target_prerequisites=tuple(prereqs),
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
        raise AssuranceCompressionGuiError(str(exc)) from exc
    assert_assurance_compression_gui_defaults(sealed)
    return sealed


# ---------------------------------------------------------------------------
# Normative catalogue recipes (plan + acceptance)
# ---------------------------------------------------------------------------


def assurance_compression_gui_operator_specs() -> (
    tuple[AssuranceCompressionGuiOperatorSpec, ...]
):
    """Return the closed, ordered set of normative operator recipes."""

    test_adeq = PropertyClass.TEST_ADEQUACY
    proof_adeq = PropertyClass.PROOF_ADEQUACY
    receipt = PropertyClass.RECEIPT_AUTHENTICITY
    capsule = PropertyClass.CAPSULE_COMPLETENESS
    data_int = PropertyClass.DATA_INTEGRITY
    gui = PropertyClass.GUI_ACTION_BINDING
    side_effect = PropertyClass.SIDE_EFFECT_OBLIGATION

    return (
        # ---- test_proof: weak / deleted / skipped tests, fixtures ----
        AssuranceCompressionGuiOperatorSpec(
            operator_id="test_weaken_assertion",
            family=AssuranceCompressionGuiFamily.WEAK_TEST,
            semantic_intent=(
                "Weaken a behavioral assertion to a tautology, type-only, or "
                "non-null check that no longer constrains the target behavior"
            ),
            syntactic_transformation="replace_behavioral_assert_with_tautology_or_type_only",
            expected_violated_property_classes=(test_adeq,),
            likely_equivalent_conditions=(
                "assertion_already_type_only",
                "target_behavior_unconstrained_by_design",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Test/proof class: weak assertions",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="test_delete_test_case",
            family=AssuranceCompressionGuiFamily.DELETED_TEST,
            semantic_intent=(
                "Delete a required test case or assertion body so the suite "
                "no longer exercises the claimed behavior"
            ),
            syntactic_transformation="delete_test_function_or_assertion_block",
            expected_violated_property_classes=(test_adeq,),
            likely_equivalent_conditions=(
                "test_was_duplicate_of_remaining_suite",
                "behavior_covered_by_stronger_property_test",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Test/proof class: deleted tests",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="test_permanent_skip",
            family=AssuranceCompressionGuiFamily.SKIPPED_TEST,
            semantic_intent=(
                "Mark a required test as permanently skipped or xfailed so "
                "failures never surface in the selected suite"
            ),
            syntactic_transformation="add_unconditional_skip_or_xfail_marker",
            expected_violated_property_classes=(test_adeq,),
            likely_equivalent_conditions=(
                "skip_already_required_by_platform_gate",
                "test_marked_optional_in_manifest",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Test/proof class: skipped tests",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="test_bypass_fixture",
            family=AssuranceCompressionGuiFamily.FIXTURE,
            semantic_intent=(
                "Bypass or neutralize a fixture so the target under test is "
                "never called, or success is recorded before effect observation"
            ),
            syntactic_transformation="replace_fixture_setup_with_noop_or_uncalled_stub",
            expected_violated_property_classes=(test_adeq, side_effect),
            likely_equivalent_conditions=(
                "fixture_was_already_optional",
                "target_has_no_observable_side_effects",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Test/proof class: fixtures that bypass behavior",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="test_fixture_conceals_behavior",
            family=AssuranceCompressionGuiFamily.FIXTURE,
            semantic_intent=(
                "Alter a fixture mock so it always returns success independent "
                "of the target implementation path"
            ),
            syntactic_transformation="make_fixture_mock_always_succeed_independent_of_target",
            expected_violated_property_classes=(test_adeq,),
            likely_equivalent_conditions=(
                "mock_already_behavior_independent",
                "test_only_checks_fixture_wiring",
            ),
            risk_class=MutationRiskClass.MEDIUM,
            notes="Test/proof class: behavior-independent mocks/fixtures",
        ),
        # ---- test_proof: vacuous / stale / incomplete proofs ----
        AssuranceCompressionGuiOperatorSpec(
            operator_id="proof_vacuous_impossible_assumption",
            family=AssuranceCompressionGuiFamily.VACUOUS_PROOF,
            semantic_intent=(
                "Introduce an unsatisfiable antecedent or impossible assumption "
                "so the proof discharges vacuously without constraining behavior"
            ),
            syntactic_transformation="inject_unsatisfiable_antecedent_or_impossible_assumption",
            expected_violated_property_classes=(proof_adeq,),
            likely_equivalent_conditions=(
                "modeled_state_already_empty",
                "obligation_is_vacuous_by_specification",
            ),
            risk_class=MutationRiskClass.PROOF_RECEIPT_TRUST,
            notes="Test/proof class: vacuous proofs (impossible assumptions)",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="proof_unreachable_modeled_state",
            family=AssuranceCompressionGuiFamily.VACUOUS_PROOF,
            semantic_intent=(
                "Restrict the modeled state so the proven obligation is "
                "unreachable and never exercises the claimed behavior"
            ),
            syntactic_transformation="narrow_modeled_state_to_unreachable_region",
            expected_violated_property_classes=(proof_adeq,),
            likely_equivalent_conditions=(
                "unreachable_region_already_excluded",
                "obligation_only_applies_to_unreachable_path",
            ),
            risk_class=MutationRiskClass.PROOF_RECEIPT_TRUST,
            notes="Test/proof class: vacuous proofs (unreachable)",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="proof_stale_receipt",
            family=AssuranceCompressionGuiFamily.STALE_PROOF,
            semantic_intent=(
                "Accept or present a stale proof receipt whose source root, "
                "environment CID, or parent seal no longer matches the artifact"
            ),
            syntactic_transformation="reuse_stale_proof_receipt_without_revalidation",
            expected_violated_property_classes=(proof_adeq, receipt),
            likely_equivalent_conditions=(
                "source_root_and_environment_unchanged",
                "receipt_already_fresh_for_artifact",
            ),
            risk_class=MutationRiskClass.PROOF_RECEIPT_TRUST,
            notes="Test/proof class: stale proofs",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="proof_omit_unit",
            family=AssuranceCompressionGuiFamily.INCOMPLETE_PROOF,
            semantic_intent=(
                "Omit a required proof unit from the seal or forest so "
                "completeness is claimed without covering all obligations"
            ),
            syntactic_transformation="drop_required_proof_unit_from_forest_or_receipt",
            expected_violated_property_classes=(proof_adeq, receipt),
            likely_equivalent_conditions=(
                "omitted_unit_was_optional",
                "unit_covered_by_stronger_parent_proof",
            ),
            risk_class=MutationRiskClass.PROOF_RECEIPT_TRUST,
            notes="Test/proof class: incomplete proofs (omitted unit)",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="proof_unchecked_signature",
            family=AssuranceCompressionGuiFamily.INCOMPLETE_PROOF,
            semantic_intent=(
                "Treat an unchecked or integrity-only signature as a fully "
                "verified proof of execution without authenticity checks"
            ),
            syntactic_transformation="skip_signature_verification_accept_integrity_only",
            expected_violated_property_classes=(receipt, proof_adeq),
            likely_equivalent_conditions=(
                "signature_already_verified_upstream",
                "integrity_only_evidence_is_explicit_policy",
            ),
            risk_class=MutationRiskClass.PROOF_RECEIPT_TRUST,
            notes="Test/proof class: incomplete proofs (unchecked signatures)",
        ),
        # ---- semantic_compression: capsule / dependency / context ----
        AssuranceCompressionGuiOperatorSpec(
            operator_id="sc_stale_or_wrong_root_capsule",
            family=AssuranceCompressionGuiFamily.CAPSULE_OMISSION,
            semantic_intent=(
                "Conceal a source or schema change behind a stale or "
                "wrong-root semantic capsule presented as fresh"
            ),
            syntactic_transformation="serve_stale_or_wrong_root_capsule_as_fresh",
            expected_violated_property_classes=(capsule, data_int),
            likely_equivalent_conditions=(
                "capsule_root_matches_current_source",
                "stale_capsule_already_rejected_by_governor",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Semantic compression: stale/wrong-root capsules",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="sc_heuristic_or_opaque_as_exact",
            family=AssuranceCompressionGuiFamily.CAPSULE_OMISSION,
            semantic_intent=(
                "Substitute a heuristic capsule or opaque plugin result for "
                "exact raw-source context without disclosing confidence"
            ),
            syntactic_transformation="promote_heuristic_or_opaque_capsule_to_exact",
            expected_violated_property_classes=(capsule,),
            likely_equivalent_conditions=(
                "capsule_confidence_already_exact",
                "opaque_plugin_bound_to_exact_raw_source",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Semantic compression: heuristic/opaque-as-exact",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="sc_omit_dependency_edge",
            family=AssuranceCompressionGuiFamily.DEPENDENCY_OMISSION,
            semantic_intent=(
                "Omit a required dependency, config, or invalidation edge so "
                "selection and capsules miss a result-changing dependency"
            ),
            syntactic_transformation="drop_required_dependency_or_invalidation_edge",
            expected_violated_property_classes=(capsule, data_int),
            likely_equivalent_conditions=(
                "dependency_is_optional_and_unused",
                "invalidation_edge_redundant_with_parent",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Semantic compression: dependency omissions",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="sc_omit_config_or_exception",
            family=AssuranceCompressionGuiFamily.DEPENDENCY_OMISSION,
            semantic_intent=(
                "Omit a required config binding or exception path from the "
                "compressed context so behavior-changing cases are invisible"
            ),
            syntactic_transformation="omit_config_binding_or_exception_from_capsule",
            expected_violated_property_classes=(capsule, side_effect),
            likely_equivalent_conditions=(
                "config_already_defaulted_identically",
                "exception_path_unreachable",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Semantic compression: config/exception dependency omissions",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="sc_omit_fixture_or_effect_context",
            family=AssuranceCompressionGuiFamily.CONTEXT_OMISSION,
            semantic_intent=(
                "Omit a result-changing fixture, side effect, or selected test "
                "from compressed context so expanded context would succeed "
                "where compressed context fails to surface the change"
            ),
            syntactic_transformation="drop_fixture_effect_or_selected_test_from_context",
            expected_violated_property_classes=(capsule, test_adeq),
            likely_equivalent_conditions=(
                "omitted_context_does_not_change_result",
                "selection_already_includes_equivalent_evidence",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="Semantic compression: context/fixture/effect omissions",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="sc_selection_miss",
            family=AssuranceCompressionGuiFamily.CONTEXT_OMISSION,
            semantic_intent=(
                "Miss a relevant selected test or proof unit in compressed "
                "selection so incremental verification skips a detector that "
                "would kill the mutant"
            ),
            syntactic_transformation="exclude_relevant_selected_test_from_compression_set",
            expected_violated_property_classes=(capsule, test_adeq),
            likely_equivalent_conditions=(
                "selected_test_is_duplicate_of_included_set",
                "policy_explicitly_excludes_test_class",
            ),
            risk_class=MutationRiskClass.MEDIUM,
            notes="Semantic compression: selection misses",
        ),
        # ---- gui_action_binding: canonical only ----
        AssuranceCompressionGuiOperatorSpec(
            operator_id="gui_break_dispatchability",
            family=AssuranceCompressionGuiFamily.GUI_DISPATCHABILITY,
            semantic_intent=(
                "Break action dispatchability so a canonical GUI action no "
                "longer routes to its declared handler binding"
            ),
            syntactic_transformation="unlink_action_id_from_declared_dispatch_target",
            expected_violated_property_classes=(gui,),
            likely_equivalent_conditions=(
                "action_is_intentionally_disabled",
                "dispatch_table_has_equivalent_alias",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="GUI action binding: dispatchability only",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="gui_omit_confirmation",
            family=AssuranceCompressionGuiFamily.GUI_CONFIRMATION,
            semantic_intent=(
                "Omit a required confirmation binding for a high-risk "
                "canonical GUI action"
            ),
            syntactic_transformation="remove_required_action_confirmation_binding",
            expected_violated_property_classes=(gui, PropertyClass.POLICY_CONSTRAINT),
            likely_equivalent_conditions=(
                "confirmation_not_required_for_action",
                "confirmation_satisfied_by_parent_flow",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="GUI action binding: confirmation",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="gui_wrong_handler",
            family=AssuranceCompressionGuiFamily.GUI_HANDLER,
            semantic_intent=(
                "Bind a canonical action to the wrong handler or an incomplete "
                "handler that drops required side effects"
            ),
            syntactic_transformation="retarget_action_binding_to_wrong_or_partial_handler",
            expected_violated_property_classes=(gui, side_effect),
            likely_equivalent_conditions=(
                "handlers_are_functionally_identical",
                "wrong_handler_still_satisfies_contract",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="GUI action binding: handler",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="gui_stale_action_policy",
            family=AssuranceCompressionGuiFamily.GUI_STALE_POLICY,
            semantic_intent=(
                "Authorize a GUI action using a stale action-policy revision "
                "that no longer matches the canonical optimizer artifact"
            ),
            syntactic_transformation="accept_stale_gui_action_policy_revision",
            expected_violated_property_classes=(gui, PropertyClass.POLICY_CONSTRAINT),
            likely_equivalent_conditions=(
                "action_policy_revision_unchanged",
                "stale_policy_still_semantically_identical",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="GUI action binding: stale policy",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="gui_broken_recovery",
            family=AssuranceCompressionGuiFamily.GUI_RECOVERY,
            semantic_intent=(
                "Break recovery binding so a failed canonical action cannot "
                "return to a safe interactive state"
            ),
            syntactic_transformation="unlink_or_noop_action_recovery_handler",
            expected_violated_property_classes=(gui, PropertyClass.ERROR_HANDLING),
            likely_equivalent_conditions=(
                "recovery_not_required_for_action",
                "platform_provides_default_recovery",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="GUI action binding: recovery",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="gui_early_success_before_effect",
            family=AssuranceCompressionGuiFamily.GUI_EARLY_SUCCESS,
            semantic_intent=(
                "Report action success before the bound handler effect is "
                "observed or committed"
            ),
            syntactic_transformation="emit_action_success_before_effect_observation",
            expected_violated_property_classes=(gui, side_effect),
            likely_equivalent_conditions=(
                "effect_is_synchronous_and_already_observed",
                "success_signal_is_advisory_only",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="GUI action binding: early success",
        ),
        AssuranceCompressionGuiOperatorSpec(
            operator_id="gui_drop_critical_keyboard_access",
            family=AssuranceCompressionGuiFamily.GUI_KEYBOARD_ACCESSIBILITY,
            semantic_intent=(
                "Drop critical keyboard accessibility for a canonical action "
                "so the action is only reachable via non-keyboard paths"
            ),
            syntactic_transformation="remove_required_keyboard_binding_for_critical_action",
            expected_violated_property_classes=(gui,),
            likely_equivalent_conditions=(
                "action_not_marked_keyboard_critical",
                "equivalent_keyboard_path_remains",
            ),
            risk_class=MutationRiskClass.HIGH,
            notes="GUI action binding: critical keyboard accessibility",
        ),
    )


# ---------------------------------------------------------------------------
# Operator handles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssuranceCompressionGuiOperator(MutationOperator):
    """Declaration-backed assurance/compression/GUI operator with family binding.

    Interface membership: ``AssuranceCompressionGuiMutationOperators@1``
    catalogue entry. Does not generate source rewrites; generation is owned
    by AAE-022.
    """

    _definition: MutationOperatorDefinition
    family: str
    spec_operator_id: str

    def __post_init__(self) -> None:
        sealed = canonicalize_operator_declaration(self._definition)
        assert_assurance_compression_gui_defaults(sealed)
        try:
            family_value = AssuranceCompressionGuiFamily(self.family).value
        except ValueError as exc:
            raise AssuranceCompressionGuiError(
                f"unsupported assurance/compression/GUI family: {self.family!r}"
            ) from exc
        expected_class = _FAMILY_TO_OPERATOR_CLASS[family_value]
        if sealed.operator_class != expected_class:
            raise AssuranceCompressionGuiClassError(
                f"family {family_value!r} requires operator_class "
                f"{expected_class!r}, got {sealed.operator_class!r}"
            )
        meta_family = sealed.metadata.get("assurance_family")
        if meta_family is not None and meta_family != family_value:
            raise AssuranceCompressionGuiError(
                "definition metadata assurance_family does not match family "
                f"binding ({meta_family!r} != {family_value!r})"
            )
        object.__setattr__(self, "_definition", sealed)
        object.__setattr__(self, "family", family_value)
        if type(self.spec_operator_id) is not str or not self.spec_operator_id:
            raise AssuranceCompressionGuiError("spec_operator_id must be nonempty")
        if self.spec_operator_id != sealed.operator_id:
            raise AssuranceCompressionGuiError(
                "spec_operator_id must match definition.operator_id"
            )

    @property
    def definition(self) -> MutationOperatorDefinition:
        return self._definition

    @property
    def operator_class(self) -> str:
        return self._definition.operator_class

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
        raise AssuranceCompressionGuiError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise AssuranceCompressionGuiError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    return dict(data)


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise AssuranceCompressionGuiError(
            f"{name} must be a nonempty trimmed string"
        )
    return value


@dataclass(frozen=True, slots=True)
class AssuranceCompressionGuiMutationOperators:
    """Immutable catalogue of sealed test/proof/compression/GUI operators.

    Interface: ``AssuranceCompressionGuiMutationOperators@1``
    """

    operators: Sequence[AssuranceCompressionGuiOperator]
    producer_id: str = ASSURANCE_COMPRESSION_GUI_OPERATORS_PRODUCER
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
            raise AssuranceCompressionGuiError(
                "operators must be a sequence of AssuranceCompressionGuiOperator"
            )
        sealed: list[AssuranceCompressionGuiOperator] = []
        seen_ids: set[str] = set()
        seen_cids: set[str] = set()
        families: set[str] = set()
        classes: set[str] = set()
        for item in self.operators:
            if not isinstance(item, AssuranceCompressionGuiOperator):
                raise AssuranceCompressionGuiError(
                    "operators entries must be AssuranceCompressionGuiOperator"
                )
            definition = item.definition
            assert_assurance_compression_gui_defaults(definition)
            try:
                assert_operator_bounded(definition)
            except OperatorBoundError as exc:
                raise AssuranceCompressionGuiError(str(exc)) from exc
            if definition.operator_id in seen_ids:
                raise AssuranceCompressionGuiError(
                    f"duplicate operator_id in catalogue: {definition.operator_id}"
                )
            if definition.operator_cid in seen_cids:
                raise AssuranceCompressionGuiError(
                    f"duplicate operator_cid in catalogue: {definition.operator_cid}"
                )
            seen_ids.add(definition.operator_id)
            seen_cids.add(definition.operator_cid)
            families.add(item.family)
            classes.add(definition.operator_class)
            sealed.append(item)

        missing = REQUIRED_ASSURANCE_COMPRESSION_GUI_FAMILIES - families
        if missing:
            raise AssuranceCompressionGuiCoverageError(
                "assurance/compression/GUI catalogue missing required families: "
                + ", ".join(sorted(missing))
            )
        missing_classes = OWNED_OPERATOR_CLASSES - classes
        if missing_classes:
            raise AssuranceCompressionGuiCoverageError(
                "assurance/compression/GUI catalogue missing required operator "
                "classes: " + ", ".join(sorted(missing_classes))
            )

        ordered = tuple(
            sorted(
                sealed,
                key=lambda op: (
                    op.definition.operator_class,
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
            _reject_visual_mutation_text(
                self.notes, "notes", allow_exclusion_context=True
            )
        meta_payload = _thaw_structured(dict(self.metadata or {}))
        meta_payload.setdefault("visual_mutation_allowed", False)
        if meta_payload.get("visual_mutation_allowed") is not False:
            raise AssuranceCompressionGuiVisualMutationError(
                "catalogue metadata.visual_mutation_allowed must be false"
            )
        try:
            reject_private_model_authority_and_host_fallbacks(
                meta_payload,
                path="AssuranceCompressionGuiMutationOperators.metadata",
            )
            cid_for_structured(meta_payload)
        except AssuranceCompressionGuiError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AssuranceCompressionGuiError(
                "metadata must be DAG-JSON structured data without model authority"
            ) from exc
        object.__setattr__(self, "metadata", MappingProxyType(meta_payload))

        computed = cid_for_structured(self._identity_payload_without_catalogue_id())
        if self.catalogue_id is None:
            object.__setattr__(self, "catalogue_id", computed)
        else:
            claimed = _text(self.catalogue_id, "catalogue_id")
            if claimed != computed:
                raise AssuranceCompressionGuiError(
                    "catalogue_id identity mismatch with recomputed catalogue identity"
                )
            object.__setattr__(self, "catalogue_id", claimed)

    def _identity_payload_without_catalogue_id(self) -> dict[str, Any]:
        return {
            "schema": ASSURANCE_COMPRESSION_GUI_OPERATORS_SCHEMA,
            "interface_id": ASSURANCE_COMPRESSION_GUI_OPERATORS_INTERFACE,
            "catalogue_version": ASSURANCE_COMPRESSION_GUI_OPERATORS_VERSION,
            "operators": [
                {
                    "family": item.family,
                    "operator_class": item.definition.operator_class,
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
            "schema": ASSURANCE_COMPRESSION_GUI_OPERATORS_SCHEMA,
            "interface_id": ASSURANCE_COMPRESSION_GUI_OPERATORS_INTERFACE,
            "catalogue_version": ASSURANCE_COMPRESSION_GUI_OPERATORS_VERSION,
            "operators": [
                {
                    "family": item.family,
                    "spec_operator_id": item.spec_operator_id,
                    "operator_class": item.definition.operator_class,
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
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "AssuranceCompressionGuiMutationOperators":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != ASSURANCE_COMPRESSION_GUI_OPERATORS_SCHEMA:
            raise AssuranceCompressionGuiError(
                "unsupported AssuranceCompressionGuiMutationOperators schema version"
            )
        if payload.pop("interface_id") != ASSURANCE_COMPRESSION_GUI_OPERATORS_INTERFACE:
            raise AssuranceCompressionGuiError(
                "unsupported AssuranceCompressionGuiMutationOperators interface_id"
            )
        version = payload.pop(
            "catalogue_version", ASSURANCE_COMPRESSION_GUI_OPERATORS_VERSION
        )
        if version != ASSURANCE_COMPRESSION_GUI_OPERATORS_VERSION:
            raise AssuranceCompressionGuiError(
                "unsupported AssuranceCompressionGuiMutationOperators catalogue_version"
            )
        payload.pop("operator_cids", None)
        payload.pop("operator_count", None)
        payload.pop("families", None)
        payload.pop("operator_classes", None)
        raw_ops = payload["operators"]
        if not isinstance(raw_ops, list):
            raise AssuranceCompressionGuiError("operators must be a list")
        operators: list[AssuranceCompressionGuiOperator] = []
        for entry in raw_ops:
            if not isinstance(entry, Mapping):
                raise AssuranceCompressionGuiError(
                    "operators entries must be mappings with family and definition"
                )
            definition_raw = entry.get("definition")
            if isinstance(definition_raw, MutationOperatorDefinition):
                definition = definition_raw
            elif isinstance(definition_raw, Mapping):
                definition = MutationOperatorDefinition.from_dict(definition_raw)
            else:
                raise AssuranceCompressionGuiError(
                    "operators[].definition must be MutationOperatorDefinition or mapping"
                )
            family = entry.get("family")
            if family is None:
                family = definition.metadata.get("assurance_family")
            spec_id = entry.get("spec_operator_id", definition.operator_id)
            operators.append(
                AssuranceCompressionGuiOperator(
                    _definition=definition,
                    family=family,
                    spec_operator_id=spec_id,
                )
            )
        return cls(
            operators=operators,
            producer_id=payload.get(
                "producer_id", ASSURANCE_COMPRESSION_GUI_OPERATORS_PRODUCER
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
        if isinstance(item, AssuranceCompressionGuiOperator):
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

    def list_operators(self) -> tuple[AssuranceCompressionGuiOperator, ...]:
        return tuple(self.operators)

    def operators_for_family(
        self, family: AssuranceCompressionGuiFamily | str
    ) -> tuple[AssuranceCompressionGuiOperator, ...]:
        if isinstance(family, AssuranceCompressionGuiFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = AssuranceCompressionGuiFamily(family).value
            except ValueError as exc:
                raise AssuranceCompressionGuiError(
                    f"unsupported assurance/compression/GUI family: {family!r}"
                ) from exc
        else:
            raise AssuranceCompressionGuiError(
                "family must be AssuranceCompressionGuiFamily or str"
            )
        return tuple(item for item in self.operators if item.family == family_value)

    def operators_for_class(
        self, operator_class: OperatorClass | str
    ) -> tuple[AssuranceCompressionGuiOperator, ...]:
        if isinstance(operator_class, OperatorClass):
            class_value = operator_class.value
        elif type(operator_class) is str:
            try:
                class_value = OperatorClass(operator_class).value
            except ValueError as exc:
                raise AssuranceCompressionGuiClassError(
                    f"unsupported operator_class: {operator_class!r}"
                ) from exc
        else:
            raise AssuranceCompressionGuiError(
                "operator_class must be OperatorClass or str"
            )
        if class_value not in OWNED_OPERATOR_CLASSES:
            raise AssuranceCompressionGuiClassError(
                f"operator_class {class_value!r} is not owned by this catalogue"
            )
        return tuple(
            item
            for item in self.operators
            if item.definition.operator_class == class_value
        )

    def get(
        self,
        operator_id: str,
        operator_version: str | None = None,
    ) -> AssuranceCompressionGuiOperator:
        operator_id = _text(operator_id, "operator_id")
        matches = [
            item for item in self.operators if item.operator_id == operator_id
        ]
        if not matches:
            raise AssuranceCompressionGuiError(
                f"unknown operator_id: {operator_id}"
            )
        if operator_version is None:
            if len(matches) != 1:
                versions = ", ".join(
                    sorted({item.operator_version for item in matches})
                )
                raise AssuranceCompressionGuiError(
                    f"operator_id {operator_id} is ambiguous across versions "
                    f"({versions}); provide operator_version"
                )
            return matches[0]
        operator_version = _text(operator_version, "operator_version")
        for item in matches:
            if item.operator_version == operator_version:
                return item
        raise AssuranceCompressionGuiError(
            f"unknown operator: {operator_id}@{operator_version}"
        )

    def get_by_cid(self, operator_cid: str) -> AssuranceCompressionGuiOperator:
        operator_cid = _text(operator_cid, "operator_cid")
        for item in self.operators:
            if item.operator_cid == operator_cid:
                return item
        raise AssuranceCompressionGuiError(
            f"unknown operator_cid: {operator_cid}"
        )

    def operators_for_target(
        self, target: MutationTarget
    ) -> tuple[AssuranceCompressionGuiOperator, ...]:
        if not isinstance(target, MutationTarget):
            raise AssuranceCompressionGuiError("target must be a MutationTarget")
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
                or ASSURANCE_COMPRESSION_GUI_OPERATORS_PRODUCER,
                notes=notes if notes is not None else self.notes,
                metadata=metadata if metadata is not None else dict(self.metadata),
            )
        except OperatorRegistryError as exc:
            raise AssuranceCompressionGuiError(str(exc)) from exc

    def register_into(
        self, builder: MutationOperatorRegistryBuilder
    ) -> tuple[MutationOperatorDefinition, ...]:
        """Admit every catalogue operator into a mutable registry builder."""

        if not isinstance(builder, MutationOperatorRegistryBuilder):
            raise AssuranceCompressionGuiError(
                "builder must be a MutationOperatorRegistryBuilder"
            )
        sealed: list[MutationOperatorDefinition] = []
        for item in self.operators:
            try:
                sealed.append(builder.register(item.definition))
            except OperatorRegistryError as exc:
                raise AssuranceCompressionGuiError(str(exc)) from exc
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
        missing = REQUIRED_ASSURANCE_COMPRESSION_GUI_FAMILIES - present
        if missing:
            raise AssuranceCompressionGuiCoverageError(
                "assurance/compression/GUI catalogue missing required families: "
                + ", ".join(sorted(missing))
            )
        missing_classes = OWNED_OPERATOR_CLASSES - set(self.operator_classes())
        if missing_classes:
            raise AssuranceCompressionGuiCoverageError(
                "assurance/compression/GUI catalogue missing required operator "
                "classes: " + ", ".join(sorted(missing_classes))
            )
        # Broad visual mutation must remain absent from the catalogue.
        for item in self.operators:
            assert_no_broad_visual_mutation(item.definition)

    def assert_visual_mutation_absent(self) -> None:
        """Fail closed if any operator admits broad visual mutation."""

        for item in self.operators:
            assert_no_broad_visual_mutation(item.definition)
        if self.metadata.get("visual_mutation_allowed") is not False:
            raise AssuranceCompressionGuiVisualMutationError(
                "catalogue metadata admits visual mutation"
            )


def build_assurance_compression_gui_operators(
    specs: Iterable[AssuranceCompressionGuiOperatorSpec] | None = None,
    *,
    producer_id: str = ASSURANCE_COMPRESSION_GUI_OPERATORS_PRODUCER,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AssuranceCompressionGuiMutationOperators:
    """Build a sealed catalogue from specs (defaults: normative full set).

    The sealed ``AssuranceCompressionGuiMutationOperators@1`` interface always
    requires complete family coverage; incomplete assemblies fail closed.
    """

    recipe_list = (
        list(assurance_compression_gui_operator_specs())
        if specs is None
        else list(specs)
    )
    if not recipe_list:
        raise AssuranceCompressionGuiError(
            "assurance/compression/GUI catalogue requires at least one operator spec"
        )
    handles: list[AssuranceCompressionGuiOperator] = []
    for spec in recipe_list:
        if not isinstance(spec, AssuranceCompressionGuiOperatorSpec):
            raise AssuranceCompressionGuiError(
                "specs entries must be AssuranceCompressionGuiOperatorSpec"
            )
        definition = build_assurance_compression_gui_operator(spec)
        handles.append(
            AssuranceCompressionGuiOperator(
                _definition=definition,
                family=spec.family,
                spec_operator_id=spec.operator_id,
            )
        )
    meta = dict(metadata or {"task_id": "AAE-020"})
    meta.setdefault("visual_mutation_allowed", False)
    catalogue = AssuranceCompressionGuiMutationOperators(
        operators=handles,
        producer_id=producer_id,
        notes=notes
        if notes is not None
        else (
            "Normative test/proof, semantic-compression, and canonical GUI "
            "action-binding mutation operators; broad visual mutation absent "
            "(AAE-020)"
        ),
        metadata=meta,
    )
    catalogue.assert_complete_coverage()
    catalogue.assert_visual_mutation_absent()
    return catalogue


def default_assurance_compression_gui_operators() -> (
    AssuranceCompressionGuiMutationOperators
):
    """Return the normative sealed catalogue (stable identity across calls)."""

    return build_assurance_compression_gui_operators()


def assurance_compression_gui_operator_definitions() -> (
    tuple[MutationOperatorDefinition, ...]
):
    """Convenience: sealed definitions only, deterministic order."""

    return default_assurance_compression_gui_operators().definitions()


def assurance_compression_gui_families_covered() -> frozenset[str]:
    """Return the family set covered by the normative catalogue."""

    return frozenset(default_assurance_compression_gui_operators().families())


def visual_mutation_operators_present(
    catalogue: AssuranceCompressionGuiMutationOperators | None = None,
) -> bool:
    """Return False always for valid catalogues; raises if visual tokens leak."""

    cat = catalogue or default_assurance_compression_gui_operators()
    cat.assert_visual_mutation_absent()
    return False


__all__ = [
    "ASSURANCE_COMPRESSION_GUI_OPERATORS_INTERFACE",
    "ASSURANCE_COMPRESSION_GUI_OPERATORS_PRODUCER",
    "ASSURANCE_COMPRESSION_GUI_OPERATORS_SCHEMA",
    "ASSURANCE_COMPRESSION_GUI_OPERATORS_VERSION",
    "ASSURANCE_COMPRESSION_GUI_OPERATOR_VERSION",
    "AssuranceCompressionGuiClassError",
    "AssuranceCompressionGuiCoverageError",
    "AssuranceCompressionGuiError",
    "AssuranceCompressionGuiFamily",
    "AssuranceCompressionGuiMutationOperators",
    "AssuranceCompressionGuiOperator",
    "AssuranceCompressionGuiOperatorSpec",
    "AssuranceCompressionGuiVisualMutationError",
    "DEFAULT_ASSURANCE_RISK_CLASS",
    "DEFAULT_PROOF_RISK_CLASS",
    "FORBIDDEN_VISUAL_MUTATION_TOKENS",
    "OWNED_OPERATOR_CLASSES",
    "REQUIRED_ASSURANCE_COMPRESSION_GUI_FAMILIES",
    "assert_assurance_compression_gui_defaults",
    "assert_no_broad_visual_mutation",
    "assurance_compression_gui_families_covered",
    "assurance_compression_gui_operator_definitions",
    "assurance_compression_gui_operator_specs",
    "build_assurance_compression_gui_operator",
    "build_assurance_compression_gui_operators",
    "default_assurance_compression_gui_operators",
    "visual_mutation_operators_present",
]
