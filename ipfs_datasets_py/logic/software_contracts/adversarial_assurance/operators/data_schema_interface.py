"""Data, schema, and interface-contract mutation operators (AAE-016).

Interface: ``DataSchemaInterfaceMutationOperators@1``

Sealed, bounded, deterministic operator catalogue covering both the
``data_schema`` and ``interface_contract`` operator classes. Coverage is
normative and complete for the plan's data/schema and interface families:

Data / schema families
    required, null, default, order, version, bounds, float, Unicode, schema
    (unknown field, truncation, swapping)

Interface-contract families
    pre, post, error, exception, version, handler, semantic-result
    (structurally valid but wrong result)

Operators declare structured syntactic transformations only. Arbitrary free-form
text edits are rejected at admission (no open-ended string rewrites). Operators
never open a store, mutate production worktrees, or grant assurance authority.

Generation callables that rewrite source live in AAE-022; this module owns
canonical declarations, family coverage, and registry admission for both classes.
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

DATA_SCHEMA_INTERFACE_OPERATORS_INTERFACE: Final[str] = (
    "DataSchemaInterfaceMutationOperators@1"
)
DATA_SCHEMA_INTERFACE_OPERATORS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-"
    "data-schema-interface-mutation-operators@1"
)
DATA_SCHEMA_INTERFACE_OPERATORS_VERSION: Final[str] = "1"
DATA_SCHEMA_INTERFACE_OPERATORS_PRODUCER: Final[str] = (
    "adversarial-assurance.data-schema-interface-mutation-operators@1"
)
DATA_SCHEMA_INTERFACE_OPERATOR_VERSION: Final[str] = "1"

_DEFAULT_MAX_FILES: Final[int] = 1
_DEFAULT_MAX_SYMBOLS: Final[int] = 2
_DEFAULT_MAX_SPAN_LINES: Final[int] = 64
_DEFAULT_MAX_MUTANTS_PER_TARGET: Final[int] = 6

DEFAULT_DATA_SCHEMA_RISK_CLASS: Final[str] = MutationRiskClass.CRITICAL_INVARIANT.value
DEFAULT_INTERFACE_RISK_CLASS: Final[str] = MutationRiskClass.HIGH.value

_DEFAULT_LANGUAGES: Final[tuple[str, ...]] = ("python", "typescript")
_DEFAULT_ARTIFACT_TYPES: Final[tuple[str, ...]] = (
    "source_module",
    "schema_artifact",
    "interface_artifact",
)
_DEFAULT_PREREQUISITES: Final[tuple[str, ...]] = (
    "parsed_ast",
    "symbol_table",
    "type_check",
)

# Metadata key for family binding (avoid private-field markers).
_FAMILY_METADATA_KEY: Final[str] = "dsi_family"
_OPERATOR_CLASS_METADATA_KEY: Final[str] = "dsi_operator_class"

# Closed set of operator classes admitted by this catalogue.
ADMITTED_OPERATOR_CLASSES: Final[frozenset[str]] = frozenset(
    {
        OperatorClass.DATA_SCHEMA.value,
        OperatorClass.INTERFACE_CONTRACT.value,
    }
)

# Free-form text rewrite tokens are never admitted.
_ARBITRARY_TEXT_EDIT_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "arbitrary_text",
        "arbitrary_text_edit",
        "freeform_text",
        "freeform_string_replace",
        "free_form_text_edit",
        "regex_replace_text",
        "unstructured_text_rewrite",
        "open_ended_string_mutation",
        "text_edit_anywhere",
    }
)


class DataSchemaInterfaceError(AssuranceBaseError):
    """Raised when a data/schema/interface operator contract fails closed."""


class DataSchemaInterfaceCoverageError(DataSchemaInterfaceError):
    """Raised when the catalogue does not cover a required family."""


class DataSchemaInterfaceTextEditError(DataSchemaInterfaceError):
    """Raised when an operator declares an arbitrary free-form text edit."""


class DataSchemaInterfaceFamily(str, Enum):
    """Closed family keys required by plan acceptance for AAE-016."""

    # Data / schema
    REQUIRED = "required"
    NULL = "null"
    DEFAULT = "default"
    ORDER = "order"
    VERSION = "version"
    BOUNDS = "bounds"
    FLOAT = "float"
    UNICODE = "unicode"
    SCHEMA = "schema"
    # Interface contract
    PRE = "pre"
    POST = "post"
    ERROR = "error"
    EXCEPTION = "exception"
    HANDLER = "handler"
    SEMANTIC_RESULT = "semantic_result"


REQUIRED_DATA_SCHEMA_INTERFACE_FAMILIES: Final[frozenset[str]] = frozenset(
    item.value for item in DataSchemaInterfaceFamily
)

REQUIRED_DATA_SCHEMA_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        DataSchemaInterfaceFamily.REQUIRED.value,
        DataSchemaInterfaceFamily.NULL.value,
        DataSchemaInterfaceFamily.DEFAULT.value,
        DataSchemaInterfaceFamily.ORDER.value,
        DataSchemaInterfaceFamily.VERSION.value,
        DataSchemaInterfaceFamily.BOUNDS.value,
        DataSchemaInterfaceFamily.FLOAT.value,
        DataSchemaInterfaceFamily.UNICODE.value,
        DataSchemaInterfaceFamily.SCHEMA.value,
    }
)

REQUIRED_INTERFACE_CONTRACT_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        DataSchemaInterfaceFamily.PRE.value,
        DataSchemaInterfaceFamily.POST.value,
        DataSchemaInterfaceFamily.ERROR.value,
        DataSchemaInterfaceFamily.EXCEPTION.value,
        DataSchemaInterfaceFamily.VERSION.value,
        DataSchemaInterfaceFamily.HANDLER.value,
        DataSchemaInterfaceFamily.SEMANTIC_RESULT.value,
    }
)

_DATA_ONLY_FAMILIES: Final[frozenset[str]] = frozenset(
    REQUIRED_DATA_SCHEMA_FAMILIES
    - {DataSchemaInterfaceFamily.VERSION.value}
)
_INTERFACE_ONLY_FAMILIES: Final[frozenset[str]] = frozenset(
    REQUIRED_INTERFACE_CONTRACT_FAMILIES
    - {DataSchemaInterfaceFamily.VERSION.value}
)


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
            raise DataSchemaInterfaceError(
                f"unsupported operator_class: {value!r}"
            ) from exc
    else:
        raise DataSchemaInterfaceError(
            "operator_class must be OperatorClass or str"
        )
    if class_value not in ADMITTED_OPERATOR_CLASSES:
        raise DataSchemaInterfaceError(
            "operator_class must be data_schema or interface_contract; "
            f"got {class_value!r}"
        )
    return class_value


def _default_operator_class_for_family(family: str) -> str:
    if family in _DATA_ONLY_FAMILIES:
        return OperatorClass.DATA_SCHEMA.value
    if family in _INTERFACE_ONLY_FAMILIES:
        return OperatorClass.INTERFACE_CONTRACT.value
    # VERSION is shared; default to data_schema (interface version ops override).
    if family == DataSchemaInterfaceFamily.VERSION.value:
        return OperatorClass.DATA_SCHEMA.value
    raise DataSchemaInterfaceError(f"unsupported family for class default: {family!r}")


def assert_structured_transformation(transformation: str) -> None:
    """Fail closed when a transformation is an arbitrary free-form text edit."""

    if type(transformation) is not str or not transformation.strip():
        raise DataSchemaInterfaceError(
            "syntactic_transformation must be a nonempty string"
        )
    token = transformation.strip()
    if token != transformation:
        raise DataSchemaInterfaceError(
            "syntactic_transformation must be trimmed"
        )
    if any(char.isspace() for char in token):
        raise DataSchemaInterfaceTextEditError(
            "syntactic_transformation must not contain free-form text spans"
        )
    lowered = token.lower()
    if lowered in _ARBITRARY_TEXT_EDIT_MARKERS:
        raise DataSchemaInterfaceTextEditError(
            f"arbitrary text edit transformation is forbidden: {token!r}"
        )
    for marker in _ARBITRARY_TEXT_EDIT_MARKERS:
        if marker in lowered:
            raise DataSchemaInterfaceTextEditError(
                f"arbitrary text edit transformation is forbidden: {token!r}"
            )
    # Structured transformations are closed snake_case tokens (optionally dotted).
    for part in token.replace(".", "_").split("_"):
        if not part:
            raise DataSchemaInterfaceError(
                "syntactic_transformation must be a structured snake_case token"
            )
        if not part.isidentifier() and not part.isalnum():
            raise DataSchemaInterfaceError(
                "syntactic_transformation must be a structured token without "
                f"free-form punctuation: {token!r}"
            )


@dataclass(frozen=True, slots=True)
class DataSchemaInterfaceOperatorSpec:
    """Declarative recipe for one sealed data/schema or interface operator.

    Specs are pure data used to construct ``MutationOperatorDefinition``
    values. They are not durable CAS records.
    """

    operator_id: str
    family: DataSchemaInterfaceFamily | str
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
            raise DataSchemaInterfaceError("operator_id must be a nonempty string")

        family = self.family
        if isinstance(family, DataSchemaInterfaceFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = DataSchemaInterfaceFamily(family).value
            except ValueError as exc:
                raise DataSchemaInterfaceError(
                    f"unsupported data/schema/interface family: {family!r}"
                ) from exc
        else:
            raise DataSchemaInterfaceError(
                "family must be DataSchemaInterfaceFamily or str"
            )
        object.__setattr__(self, "family", family_value)

        if self.operator_class is None:
            class_value = _default_operator_class_for_family(family_value)
        else:
            class_value = _normalize_operator_class(self.operator_class)
        # Enforce family/class coherence (version may be either class).
        if family_value in _DATA_ONLY_FAMILIES and (
            class_value != OperatorClass.DATA_SCHEMA.value
        ):
            raise DataSchemaInterfaceError(
                f"family {family_value!r} requires operator_class data_schema"
            )
        if family_value in _INTERFACE_ONLY_FAMILIES and (
            class_value != OperatorClass.INTERFACE_CONTRACT.value
        ):
            raise DataSchemaInterfaceError(
                f"family {family_value!r} requires operator_class interface_contract"
            )
        object.__setattr__(self, "operator_class", class_value)

        if self.risk_class is None:
            risk_value = (
                DEFAULT_DATA_SCHEMA_RISK_CLASS
                if class_value == OperatorClass.DATA_SCHEMA.value
                else DEFAULT_INTERFACE_RISK_CLASS
            )
        else:
            risk = self.risk_class
            if isinstance(risk, MutationRiskClass):
                risk_value = risk.value
            elif type(risk) is str:
                try:
                    risk_value = MutationRiskClass(risk).value
                except ValueError as exc:
                    raise DataSchemaInterfaceError(
                        f"unsupported risk_class: {risk!r}"
                    ) from exc
            else:
                raise DataSchemaInterfaceError(
                    "risk_class must be MutationRiskClass or str"
                )
        object.__setattr__(self, "risk_class", risk_value)

        if type(self.semantic_intent) is not str or not self.semantic_intent.strip():
            raise DataSchemaInterfaceError("semantic_intent must be nonempty")
        assert_structured_transformation(self.syntactic_transformation)

        props = tuple(self.expected_violated_property_classes)
        if not props:
            raise DataSchemaInterfaceError(
                "expected_violated_property_classes must not be empty"
            )
        object.__setattr__(self, "expected_violated_property_classes", props)

        equiv = tuple(self.likely_equivalent_conditions or ())
        if not equiv:
            raise DataSchemaInterfaceError(
                "likely_equivalent_conditions must provide equivalence hints"
            )
        for condition in equiv:
            if type(condition) is not str or not condition.strip():
                raise DataSchemaInterfaceError(
                    "likely_equivalent_conditions entries must be nonempty strings"
                )
        object.__setattr__(self, "likely_equivalent_conditions", equiv)

        if (
            type(self.max_mutants_per_target) is not int
            or isinstance(self.max_mutants_per_target, bool)
            or self.max_mutants_per_target < 1
        ):
            raise DataSchemaInterfaceError(
                "max_mutants_per_target must be a positive integer"
            )

        meta = dict(self.metadata or {})
        meta.setdefault(_FAMILY_METADATA_KEY, family_value)
        meta.setdefault(_OPERATOR_CLASS_METADATA_KEY, class_value)
        try:
            reject_private_model_authority_and_host_fallbacks(
                meta, path="DataSchemaInterfaceOperatorSpec.metadata"
            )
            cid_for_structured(meta)
        except Exception as exc:  # noqa: BLE001
            raise DataSchemaInterfaceError(
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


def assert_data_schema_interface_operator_defaults(
    operator: MutationOperatorDefinition,
) -> None:
    """Fail closed when an operator lacks class, intent, or structured transform."""

    if not isinstance(operator, MutationOperatorDefinition):
        raise DataSchemaInterfaceError(
            "operator must be a sealed MutationOperatorDefinition"
        )
    if operator.operator_class not in ADMITTED_OPERATOR_CLASSES:
        raise DataSchemaInterfaceError(
            "operator_class must be data_schema or interface_contract"
        )
    if not operator.semantic_intent or not str(operator.semantic_intent).strip():
        raise DataSchemaInterfaceError(
            f"operator {operator.operator_id} must declare semantic_intent"
        )
    if not operator.likely_equivalent_conditions:
        raise DataSchemaInterfaceError(
            f"operator {operator.operator_id} must declare equivalence hints "
            "(likely_equivalent_conditions)"
        )
    assert_structured_transformation(str(operator.syntactic_transformation))

    props = set(operator.expected_violated_property_classes)
    if operator.operator_class == OperatorClass.DATA_SCHEMA.value:
        allowed = {
            PropertyClass.DATA_INTEGRITY.value,
            PropertyClass.SCHEMA_CONTRACT.value,
        }
        if not (props & allowed):
            raise DataSchemaInterfaceError(
                f"operator {operator.operator_id} must expect data_integrity or "
                "schema_contract property violations"
            )
    else:
        allowed = {
            PropertyClass.INTERFACE_CONTRACT.value,
            PropertyClass.ERROR_HANDLING.value,
            PropertyClass.DATA_INTEGRITY.value,
            PropertyClass.SCHEMA_CONTRACT.value,
        }
        if PropertyClass.INTERFACE_CONTRACT.value not in props and not (
            props & allowed
        ):
            raise DataSchemaInterfaceError(
                f"operator {operator.operator_id} must expect interface_contract "
                "or related property violations"
            )
        if PropertyClass.INTERFACE_CONTRACT.value not in props:
            # Interface-class operators must always list interface_contract.
            raise DataSchemaInterfaceError(
                f"operator {operator.operator_id} must expect interface_contract "
                "property violations"
            )


def build_data_schema_interface_operator(
    spec: DataSchemaInterfaceOperatorSpec,
    *,
    supported_languages: Sequence[str] | None = None,
    supported_artifact_types: Sequence[str] | None = None,
    target_prerequisites: Sequence[str] | None = None,
    scope_limits: ScopeLimits | None = None,
    rollback: RollbackDeclaration | None = None,
    required_sandbox: SandboxRequirement | None = None,
    operator_version: str = DATA_SCHEMA_INTERFACE_OPERATOR_VERSION,
) -> MutationOperatorDefinition:
    """Seal one data/schema or interface-contract operator under defaults."""

    if not isinstance(spec, DataSchemaInterfaceOperatorSpec):
        raise DataSchemaInterfaceError(
            "spec must be a DataSchemaInterfaceOperatorSpec"
        )
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
        raise DataSchemaInterfaceError(str(exc)) from exc
    assert_data_schema_interface_operator_defaults(sealed)
    return sealed


# ---------------------------------------------------------------------------
# Normative catalogue recipes (plan acceptance families)
# ---------------------------------------------------------------------------


def data_schema_interface_operator_specs() -> tuple[
    DataSchemaInterfaceOperatorSpec, ...
]:
    """Return the closed, ordered set of normative operator recipes."""

    data_int = PropertyClass.DATA_INTEGRITY
    schema = PropertyClass.SCHEMA_CONTRACT
    iface = PropertyClass.INTERFACE_CONTRACT
    error_handling = PropertyClass.ERROR_HANDLING

    return (
        # --- required --------------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_drop_required_field",
            family=DataSchemaInterfaceFamily.REQUIRED,
            semantic_intent=(
                "Drop a required field from a payload or schema so consumers "
                "receive an incomplete record that still type-checks partially"
            ),
            syntactic_transformation="remove_required_field_from_object",
            expected_violated_property_classes=(schema, data_int),
            likely_equivalent_conditions=(
                "field_is_already_optional_by_schema",
                "field_value_is_statically_unused",
                "consumer_ignores_missing_required_fields",
            ),
            notes="Omit required field",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_mark_required_optional",
            family=DataSchemaInterfaceFamily.REQUIRED,
            semantic_intent=(
                "Weaken a required field constraint to optional so missing "
                "values are accepted as valid schema instances"
            ),
            syntactic_transformation="replace_required_constraint_with_optional",
            expected_violated_property_classes=(schema,),
            likely_equivalent_conditions=(
                "field_already_optional",
                "all_producers_always_populate_field",
            ),
            notes="Required becomes optional",
        ),
        # --- null ------------------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_force_null_value",
            family=DataSchemaInterfaceFamily.NULL,
            semantic_intent=(
                "Replace a non-null field value with null where the schema or "
                "contract forbids nullability"
            ),
            syntactic_transformation="replace_field_value_with_null",
            expected_violated_property_classes=(schema, data_int),
            likely_equivalent_conditions=(
                "field_is_nullable_by_schema",
                "null_is_observationally_identical_to_default",
            ),
            notes="Inject forbidden null",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_accept_null_where_forbidden",
            family=DataSchemaInterfaceFamily.NULL,
            semantic_intent=(
                "Relax a non-null schema constraint so null values pass "
                "validation without conversion"
            ),
            syntactic_transformation="drop_non_null_schema_constraint",
            expected_violated_property_classes=(schema,),
            likely_equivalent_conditions=(
                "producers_never_emit_null",
                "downstream_null_handling_already_present",
            ),
            notes="Accept null where forbidden",
        ),
        # --- default ---------------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_suppress_default_application",
            family=DataSchemaInterfaceFamily.DEFAULT,
            semantic_intent=(
                "Suppress application of a schema or constructor default so "
                "absent fields remain unset instead of receiving the default"
            ),
            syntactic_transformation="omit_default_value_injection",
            expected_violated_property_classes=(schema, data_int),
            likely_equivalent_conditions=(
                "default_is_already_absent",
                "absent_and_default_are_observationally_identical",
            ),
            notes="Skip default injection",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_wrong_default_value",
            family=DataSchemaInterfaceFamily.DEFAULT,
            semantic_intent=(
                "Substitute an incorrect default value that remains type-valid "
                "but violates domain semantics"
            ),
            syntactic_transformation="replace_default_with_type_compatible_wrong_value",
            expected_violated_property_classes=(data_int, schema),
            likely_equivalent_conditions=(
                "default_is_never_used",
                "wrong_default_matches_all_observed_inputs",
            ),
            notes="Wrong but type-compatible default",
        ),
        # --- order -----------------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_reorder_object_fields",
            family=DataSchemaInterfaceFamily.ORDER,
            semantic_intent=(
                "Reorder object fields or map entries when consumers rely on "
                "stable key order for hashing, encoding, or equality"
            ),
            syntactic_transformation="permute_object_field_order",
            expected_violated_property_classes=(data_int, schema),
            likely_equivalent_conditions=(
                "consumers_treat_order_as_irrelevant",
                "canonicalization_already_sorts_keys",
            ),
            notes="Field order permutation",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_reorder_array_elements",
            family=DataSchemaInterfaceFamily.ORDER,
            semantic_intent=(
                "Reorder array or sequence elements when positional order is "
                "semantically significant"
            ),
            syntactic_transformation="permute_array_element_order",
            expected_violated_property_classes=(data_int,),
            likely_equivalent_conditions=(
                "array_is_order_insensitive_set",
                "array_length_is_zero_or_one",
            ),
            notes="Array order permutation",
        ),
        # --- version (data / schema) -----------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_mismatch_schema_version",
            family=DataSchemaInterfaceFamily.VERSION,
            operator_class=OperatorClass.DATA_SCHEMA,
            semantic_intent=(
                "Bind or advertise a schema version that does not match the "
                "payload shape or negotiated protocol version"
            ),
            syntactic_transformation="replace_schema_version_token",
            expected_violated_property_classes=(schema, data_int),
            likely_equivalent_conditions=(
                "version_token_is_ignored",
                "all_versions_share_identical_shape",
            ),
            notes="Schema version mismatch",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_skip_version_gate",
            family=DataSchemaInterfaceFamily.VERSION,
            operator_class=OperatorClass.DATA_SCHEMA,
            semantic_intent=(
                "Skip a schema version compatibility gate so unsupported "
                "revisions are accepted without migration"
            ),
            syntactic_transformation="bypass_schema_version_compatibility_check",
            expected_violated_property_classes=(schema,),
            likely_equivalent_conditions=(
                "only_one_version_exists",
                "compatibility_check_is_redundant",
            ),
            notes="Bypass schema version gate",
        ),
        # --- bounds ----------------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_relax_min_bound",
            family=DataSchemaInterfaceFamily.BOUNDS,
            semantic_intent=(
                "Relax a minimum numeric or length bound so under-range values "
                "are accepted"
            ),
            syntactic_transformation="decrease_or_remove_minimum_constraint",
            expected_violated_property_classes=(schema, data_int),
            likely_equivalent_conditions=(
                "producers_never_emit_under_range",
                "minimum_already_unbounded",
            ),
            notes="Relax minimum bound",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_relax_max_bound",
            family=DataSchemaInterfaceFamily.BOUNDS,
            semantic_intent=(
                "Relax a maximum numeric or length bound so over-range values "
                "are accepted"
            ),
            syntactic_transformation="increase_or_remove_maximum_constraint",
            expected_violated_property_classes=(schema, data_int),
            likely_equivalent_conditions=(
                "producers_never_emit_over_range",
                "maximum_already_unbounded",
            ),
            notes="Relax maximum bound",
        ),
        # --- float -----------------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_float_equality_without_epsilon",
            family=DataSchemaInterfaceFamily.FLOAT,
            semantic_intent=(
                "Replace epsilon-tolerant floating comparison with exact "
                "equality so near-equal values fail or diverge"
            ),
            syntactic_transformation="replace_epsilon_compare_with_exact_eq",
            expected_violated_property_classes=(data_int,),
            likely_equivalent_conditions=(
                "values_are_always_integral",
                "epsilon_window_is_zero",
            ),
            notes="Exact float equality",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_inject_nan_or_inf",
            family=DataSchemaInterfaceFamily.FLOAT,
            semantic_intent=(
                "Inject NaN or infinity into a floating field that contracts "
                "require finite numbers"
            ),
            syntactic_transformation="replace_finite_float_with_nan_or_inf",
            expected_violated_property_classes=(data_int, schema),
            likely_equivalent_conditions=(
                "schema_already_allows_nonfinite",
                "consumers_treat_nan_as_sentinel_equivalently",
            ),
            notes="Non-finite float injection",
        ),
        # --- Unicode ---------------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_unicode_normalization_change",
            family=DataSchemaInterfaceFamily.UNICODE,
            semantic_intent=(
                "Change Unicode normalization form (for example NFC to NFD) so "
                "string identity, hashing, or equality diverges"
            ),
            syntactic_transformation="rewrite_string_unicode_normalization_form",
            expected_violated_property_classes=(data_int,),
            likely_equivalent_conditions=(
                "strings_are_already_ascii_only",
                "consumers_normalize_before_compare",
            ),
            notes="Unicode normalization mutation",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_unicode_homoglyph_swap",
            family=DataSchemaInterfaceFamily.UNICODE,
            semantic_intent=(
                "Substitute a look-alike Unicode homoglyph in an identifier or "
                "token while preserving visual shape"
            ),
            syntactic_transformation="replace_codepoint_with_homoglyph",
            expected_violated_property_classes=(data_int, schema),
            likely_equivalent_conditions=(
                "field_is_display_only_never_compared",
                "normalization_and_confusable_checks_already_applied",
            ),
            notes="Homoglyph substitution",
        ),
        # --- schema (unknown field, truncation, swapping) --------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_inject_unknown_field",
            family=DataSchemaInterfaceFamily.SCHEMA,
            semantic_intent=(
                "Inject an unknown or additionalProperties-violating field into "
                "a closed object schema"
            ),
            syntactic_transformation="insert_unknown_object_field",
            expected_violated_property_classes=(schema,),
            likely_equivalent_conditions=(
                "schema_allows_additional_properties",
                "unknown_fields_are_stripped_before_use",
            ),
            notes="Unknown field injection",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_truncate_payload_field",
            family=DataSchemaInterfaceFamily.SCHEMA,
            semantic_intent=(
                "Truncate a string, bytes, or array field below the length "
                "required by the schema or consumer"
            ),
            syntactic_transformation="truncate_field_below_required_length",
            expected_violated_property_classes=(schema, data_int),
            likely_equivalent_conditions=(
                "consumers_only_read_prefix",
                "truncated_suffix_is_padding",
            ),
            notes="Field truncation",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ds_swap_sibling_fields",
            family=DataSchemaInterfaceFamily.SCHEMA,
            semantic_intent=(
                "Swap values of two sibling fields with compatible types so the "
                "structure remains schema-valid but semantics are inverted"
            ),
            syntactic_transformation="swap_sibling_field_values",
            expected_violated_property_classes=(data_int, schema),
            likely_equivalent_conditions=(
                "sibling_fields_are_observationally_symmetric",
                "swapped_values_are_always_equal",
            ),
            notes="Sibling field value swap",
        ),
        # --- pre (parameter / precondition) ----------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_drop_precondition",
            family=DataSchemaInterfaceFamily.PRE,
            semantic_intent=(
                "Remove or always-true a parameter precondition so invalid "
                "inputs proceed into the implementation"
            ),
            syntactic_transformation="replace_precondition_check_with_true",
            expected_violated_property_classes=(iface,),
            likely_equivalent_conditions=(
                "precondition_is_statically_always_true",
                "callers_already_guarantee_precondition",
            ),
            notes="Drop precondition",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_wrong_parameter_type_coercion",
            family=DataSchemaInterfaceFamily.PRE,
            semantic_intent=(
                "Coerce or accept a parameter under a wider type than the "
                "interface contract declares"
            ),
            syntactic_transformation="widen_parameter_type_acceptance",
            expected_violated_property_classes=(iface, schema),
            likely_equivalent_conditions=(
                "callers_only_pass_declared_type",
                "coercion_is_identity_for_all_inputs",
            ),
            notes="Widen parameter acceptance",
        ),
        # --- post ------------------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_drop_postcondition",
            family=DataSchemaInterfaceFamily.POST,
            semantic_intent=(
                "Remove a return-value postcondition so results that violate "
                "the declared contract are returned unchallenged"
            ),
            syntactic_transformation="omit_postcondition_assertion",
            expected_violated_property_classes=(iface,),
            likely_equivalent_conditions=(
                "postcondition_is_statically_always_true",
                "implementation_cannot_violate_postcondition",
            ),
            notes="Drop postcondition",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_weaken_postcondition",
            family=DataSchemaInterfaceFamily.POST,
            semantic_intent=(
                "Weaken a postcondition bound or predicate so a larger set of "
                "results is considered contract-satisfying"
            ),
            syntactic_transformation="relax_postcondition_predicate",
            expected_violated_property_classes=(iface, data_int),
            likely_equivalent_conditions=(
                "weakened_predicate_is_equivalent_on_reachable_results",
                "postcondition_is_unused_by_callers",
            ),
            notes="Weaken postcondition",
        ),
        # --- error -----------------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_wrong_error_code",
            family=DataSchemaInterfaceFamily.ERROR,
            semantic_intent=(
                "Return a different but declared error code or status for a "
                "failure path so callers branch incorrectly"
            ),
            syntactic_transformation="replace_error_code_with_alternate_declared_code",
            expected_violated_property_classes=(iface, error_handling),
            likely_equivalent_conditions=(
                "callers_treat_all_error_codes_identically",
                "alternate_code_is_alias_of_original",
            ),
            notes="Wrong declared error code",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_suppress_declared_error",
            family=DataSchemaInterfaceFamily.ERROR,
            semantic_intent=(
                "Suppress a declared error path and return success or a void "
                "result instead of the contracted failure signal"
            ),
            syntactic_transformation="replace_error_return_with_success_path",
            expected_violated_property_classes=(iface, error_handling),
            likely_equivalent_conditions=(
                "error_path_is_statically_unreachable",
                "success_result_is_idempotent_with_error_recovery",
            ),
            notes="Suppress declared error",
        ),
        # --- exception -------------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_wrong_exception_type",
            family=DataSchemaInterfaceFamily.EXCEPTION,
            semantic_intent=(
                "Raise a different exception type than the interface documents "
                "while remaining within a broad exception hierarchy"
            ),
            syntactic_transformation="replace_exception_type_with_sibling_type",
            expected_violated_property_classes=(iface, error_handling),
            likely_equivalent_conditions=(
                "callers_catch_common_base_type_only",
                "exception_types_are_aliases",
            ),
            notes="Wrong exception type",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_swallow_declared_exception",
            family=DataSchemaInterfaceFamily.EXCEPTION,
            semantic_intent=(
                "Catch and swallow a declared exception without re-raise or "
                "mapped error, violating the exception contract"
            ),
            syntactic_transformation="catch_and_suppress_declared_exception",
            expected_violated_property_classes=(iface, error_handling),
            likely_equivalent_conditions=(
                "exception_never_raised_under_context",
                "suppression_matches_documented_best_effort_semantics",
            ),
            notes="Swallow declared exception",
        ),
        # --- version (interface) ---------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_mismatch_interface_version",
            family=DataSchemaInterfaceFamily.VERSION,
            operator_class=OperatorClass.INTERFACE_CONTRACT,
            semantic_intent=(
                "Advertise or negotiate an interface version that does not "
                "match the implemented operation set"
            ),
            syntactic_transformation="replace_interface_version_token",
            expected_violated_property_classes=(iface,),
            likely_equivalent_conditions=(
                "version_token_is_ignored_by_peers",
                "all_interface_versions_are_wire_compatible",
            ),
            notes="Interface version mismatch",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_skip_interface_version_check",
            family=DataSchemaInterfaceFamily.VERSION,
            operator_class=OperatorClass.INTERFACE_CONTRACT,
            semantic_intent=(
                "Skip interface version negotiation or compatibility checks so "
                "incompatible peers proceed"
            ),
            syntactic_transformation="bypass_interface_version_negotiation",
            expected_violated_property_classes=(iface,),
            likely_equivalent_conditions=(
                "only_one_interface_version_exists",
                "negotiation_is_redundant_with_transport_binding",
            ),
            notes="Skip interface version check",
        ),
        # --- handler ---------------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_wrong_handler_binding",
            family=DataSchemaInterfaceFamily.HANDLER,
            semantic_intent=(
                "Bind an operation or message type to a different handler than "
                "the interface registry declares"
            ),
            syntactic_transformation="rewire_operation_to_alternate_handler",
            expected_violated_property_classes=(iface,),
            likely_equivalent_conditions=(
                "alternate_handler_is_observationally_identical",
                "operation_is_never_dispatched",
            ),
            notes="Wrong handler binding",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_drop_handler_registration",
            family=DataSchemaInterfaceFamily.HANDLER,
            semantic_intent=(
                "Omit registration of a required handler so dispatch falls "
                "through to a default or no-op path"
            ),
            syntactic_transformation="omit_handler_registry_entry",
            expected_violated_property_classes=(iface, error_handling),
            likely_equivalent_conditions=(
                "default_handler_implements_same_contract",
                "operation_is_never_invoked",
            ),
            notes="Drop handler registration",
        ),
        # --- semantic-result -------------------------------------------------
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_structurally_valid_wrong_result",
            family=DataSchemaInterfaceFamily.SEMANTIC_RESULT,
            semantic_intent=(
                "Return a structurally schema-valid result whose semantic "
                "content violates the operation contract"
            ),
            syntactic_transformation="replace_result_with_schema_valid_wrong_payload",
            expected_violated_property_classes=(iface, data_int),
            likely_equivalent_conditions=(
                "result_is_never_inspected_by_callers",
                "wrong_payload_is_semantically_equivalent",
            ),
            notes="Structurally valid but wrong result",
        ),
        DataSchemaInterfaceOperatorSpec(
            operator_id="ic_success_with_error_semantics",
            family=DataSchemaInterfaceFamily.SEMANTIC_RESULT,
            semantic_intent=(
                "Return a success envelope whose body encodes failure semantics "
                "or partial results as if complete"
            ),
            syntactic_transformation="wrap_failure_semantics_in_success_envelope",
            expected_violated_property_classes=(iface, error_handling),
            likely_equivalent_conditions=(
                "callers_only_check_envelope_status",
                "body_failure_flags_are_always_false",
            ),
            notes="Success envelope with failure semantics",
        ),
    )


# ---------------------------------------------------------------------------
# Operator handles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DataSchemaInterfaceOperator(MutationOperator):
    """Declaration-backed data/schema or interface operator with family binding.

    Interface membership: ``DataSchemaInterfaceMutationOperators@1`` catalogue
    entry. Does not generate source rewrites; generation is owned by AAE-022.
    """

    _definition: MutationOperatorDefinition
    family: str
    spec_operator_id: str

    def __post_init__(self) -> None:
        sealed = canonicalize_operator_declaration(self._definition)
        assert_data_schema_interface_operator_defaults(sealed)
        if sealed.operator_class not in ADMITTED_OPERATOR_CLASSES:
            raise DataSchemaInterfaceError(
                "DataSchemaInterfaceOperator requires operator_class "
                "data_schema or interface_contract"
            )
        try:
            family_value = DataSchemaInterfaceFamily(self.family).value
        except ValueError as exc:
            raise DataSchemaInterfaceError(
                f"unsupported data/schema/interface family: {self.family!r}"
            ) from exc
        meta_family = sealed.metadata.get(_FAMILY_METADATA_KEY)
        if meta_family is not None and meta_family != family_value:
            raise DataSchemaInterfaceError(
                "definition metadata dsi_family does not match family binding "
                f"({meta_family!r} != {family_value!r})"
            )
        meta_class = sealed.metadata.get(_OPERATOR_CLASS_METADATA_KEY)
        if meta_class is not None and meta_class != sealed.operator_class:
            raise DataSchemaInterfaceError(
                "definition metadata dsi_operator_class does not match "
                f"operator_class ({meta_class!r} != {sealed.operator_class!r})"
            )
        object.__setattr__(self, "_definition", sealed)
        object.__setattr__(self, "family", family_value)
        if type(self.spec_operator_id) is not str or not self.spec_operator_id:
            raise DataSchemaInterfaceError("spec_operator_id must be nonempty")
        if self.spec_operator_id != sealed.operator_id:
            raise DataSchemaInterfaceError(
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
        raise DataSchemaInterfaceError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise DataSchemaInterfaceError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    return dict(data)


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise DataSchemaInterfaceError(f"{name} must be a nonempty trimmed string")
    return value


@dataclass(frozen=True, slots=True)
class DataSchemaInterfaceMutationOperators:
    """Immutable catalogue of sealed data/schema and interface operators.

    Interface: ``DataSchemaInterfaceMutationOperators@1``
    """

    operators: Sequence[DataSchemaInterfaceOperator]
    producer_id: str = DATA_SCHEMA_INTERFACE_OPERATORS_PRODUCER
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
            raise DataSchemaInterfaceError(
                "operators must be a sequence of DataSchemaInterfaceOperator"
            )
        sealed: list[DataSchemaInterfaceOperator] = []
        seen_ids: set[str] = set()
        seen_cids: set[str] = set()
        families: set[str] = set()
        classes: set[str] = set()
        for item in self.operators:
            if not isinstance(item, DataSchemaInterfaceOperator):
                raise DataSchemaInterfaceError(
                    "operators entries must be DataSchemaInterfaceOperator"
                )
            definition = item.definition
            assert_data_schema_interface_operator_defaults(definition)
            try:
                assert_operator_bounded(definition)
            except OperatorBoundError as exc:
                raise DataSchemaInterfaceError(str(exc)) from exc
            if definition.operator_id in seen_ids:
                raise DataSchemaInterfaceError(
                    f"duplicate operator_id in catalogue: {definition.operator_id}"
                )
            if definition.operator_cid in seen_cids:
                raise DataSchemaInterfaceError(
                    f"duplicate operator_cid in catalogue: {definition.operator_cid}"
                )
            seen_ids.add(definition.operator_id)
            seen_cids.add(definition.operator_cid)
            families.add(item.family)
            classes.add(definition.operator_class)
            sealed.append(item)

        missing = REQUIRED_DATA_SCHEMA_INTERFACE_FAMILIES - families
        if missing:
            raise DataSchemaInterfaceCoverageError(
                "data/schema/interface catalogue missing required families: "
                + ", ".join(sorted(missing))
            )
        missing_classes = ADMITTED_OPERATOR_CLASSES - classes
        if missing_classes:
            raise DataSchemaInterfaceCoverageError(
                "data/schema/interface catalogue missing required operator "
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
                meta_payload, path="DataSchemaInterfaceMutationOperators.metadata"
            )
            cid_for_structured(meta_payload)
        except Exception as exc:  # noqa: BLE001
            raise DataSchemaInterfaceError(
                "metadata must be DAG-JSON structured data without model authority"
            ) from exc
        object.__setattr__(self, "metadata", MappingProxyType(meta_payload))

        computed = cid_for_structured(self._identity_payload_without_catalogue_id())
        if self.catalogue_id is None:
            object.__setattr__(self, "catalogue_id", computed)
        else:
            claimed = _text(self.catalogue_id, "catalogue_id")
            if claimed != computed:
                raise DataSchemaInterfaceError(
                    "catalogue_id identity mismatch with recomputed catalogue identity"
                )
            object.__setattr__(self, "catalogue_id", claimed)

    def _identity_payload_without_catalogue_id(self) -> dict[str, Any]:
        return {
            "schema": DATA_SCHEMA_INTERFACE_OPERATORS_SCHEMA,
            "interface_id": DATA_SCHEMA_INTERFACE_OPERATORS_INTERFACE,
            "catalogue_version": DATA_SCHEMA_INTERFACE_OPERATORS_VERSION,
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
            "schema": DATA_SCHEMA_INTERFACE_OPERATORS_SCHEMA,
            "interface_id": DATA_SCHEMA_INTERFACE_OPERATORS_INTERFACE,
            "catalogue_version": DATA_SCHEMA_INTERFACE_OPERATORS_VERSION,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "DataSchemaInterfaceMutationOperators":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != DATA_SCHEMA_INTERFACE_OPERATORS_SCHEMA:
            raise DataSchemaInterfaceError(
                "unsupported DataSchemaInterfaceMutationOperators schema version"
            )
        if payload.pop("interface_id") != DATA_SCHEMA_INTERFACE_OPERATORS_INTERFACE:
            raise DataSchemaInterfaceError(
                "unsupported DataSchemaInterfaceMutationOperators interface_id"
            )
        version = payload.pop(
            "catalogue_version", DATA_SCHEMA_INTERFACE_OPERATORS_VERSION
        )
        if version != DATA_SCHEMA_INTERFACE_OPERATORS_VERSION:
            raise DataSchemaInterfaceError(
                "unsupported DataSchemaInterfaceMutationOperators catalogue_version"
            )
        payload.pop("operator_cids", None)
        payload.pop("operator_count", None)
        payload.pop("families", None)
        payload.pop("operator_classes", None)
        raw_ops = payload["operators"]
        if not isinstance(raw_ops, list):
            raise DataSchemaInterfaceError("operators must be a list")
        operators: list[DataSchemaInterfaceOperator] = []
        for entry in raw_ops:
            if not isinstance(entry, Mapping):
                raise DataSchemaInterfaceError(
                    "operators entries must be mappings with family and definition"
                )
            definition_raw = entry.get("definition")
            if isinstance(definition_raw, MutationOperatorDefinition):
                definition = definition_raw
            elif isinstance(definition_raw, Mapping):
                definition = MutationOperatorDefinition.from_dict(definition_raw)
            else:
                raise DataSchemaInterfaceError(
                    "operators[].definition must be MutationOperatorDefinition or mapping"
                )
            family = entry.get("family")
            if family is None:
                family = definition.metadata.get(_FAMILY_METADATA_KEY)
            spec_id = entry.get("spec_operator_id", definition.operator_id)
            operators.append(
                DataSchemaInterfaceOperator(
                    _definition=definition,
                    family=family,
                    spec_operator_id=spec_id,
                )
            )
        return cls(
            operators=operators,
            producer_id=payload.get(
                "producer_id", DATA_SCHEMA_INTERFACE_OPERATORS_PRODUCER
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
        if isinstance(item, DataSchemaInterfaceOperator):
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

    def list_operators(self) -> tuple[DataSchemaInterfaceOperator, ...]:
        return tuple(self.operators)

    def operators_for_family(
        self, family: DataSchemaInterfaceFamily | str
    ) -> tuple[DataSchemaInterfaceOperator, ...]:
        if isinstance(family, DataSchemaInterfaceFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = DataSchemaInterfaceFamily(family).value
            except ValueError as exc:
                raise DataSchemaInterfaceError(
                    f"unsupported data/schema/interface family: {family!r}"
                ) from exc
        else:
            raise DataSchemaInterfaceError(
                "family must be DataSchemaInterfaceFamily or str"
            )
        return tuple(item for item in self.operators if item.family == family_value)

    def operators_for_class(
        self, operator_class: OperatorClass | str
    ) -> tuple[DataSchemaInterfaceOperator, ...]:
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
    ) -> DataSchemaInterfaceOperator:
        operator_id = _text(operator_id, "operator_id")
        matches = [
            item for item in self.operators if item.operator_id == operator_id
        ]
        if not matches:
            raise DataSchemaInterfaceError(f"unknown operator_id: {operator_id}")
        if operator_version is None:
            if len(matches) != 1:
                versions = ", ".join(
                    sorted({item.operator_version for item in matches})
                )
                raise DataSchemaInterfaceError(
                    f"operator_id {operator_id} is ambiguous across versions "
                    f"({versions}); provide operator_version"
                )
            return matches[0]
        operator_version = _text(operator_version, "operator_version")
        for item in matches:
            if item.operator_version == operator_version:
                return item
        raise DataSchemaInterfaceError(
            f"unknown operator: {operator_id}@{operator_version}"
        )

    def get_by_cid(self, operator_cid: str) -> DataSchemaInterfaceOperator:
        operator_cid = _text(operator_cid, "operator_cid")
        for item in self.operators:
            if item.operator_cid == operator_cid:
                return item
        raise DataSchemaInterfaceError(f"unknown operator_cid: {operator_cid}")

    def operators_for_target(
        self, target: MutationTarget
    ) -> tuple[DataSchemaInterfaceOperator, ...]:
        if not isinstance(target, MutationTarget):
            raise DataSchemaInterfaceError("target must be a MutationTarget")
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
                producer_id=producer_id or DATA_SCHEMA_INTERFACE_OPERATORS_PRODUCER,
                notes=notes if notes is not None else self.notes,
                metadata=metadata if metadata is not None else dict(self.metadata),
            )
        except OperatorRegistryError as exc:
            raise DataSchemaInterfaceError(str(exc)) from exc

    def register_into(
        self, builder: MutationOperatorRegistryBuilder
    ) -> tuple[MutationOperatorDefinition, ...]:
        """Admit every catalogue operator into a mutable registry builder."""

        if not isinstance(builder, MutationOperatorRegistryBuilder):
            raise DataSchemaInterfaceError(
                "builder must be a MutationOperatorRegistryBuilder"
            )
        sealed: list[MutationOperatorDefinition] = []
        for item in self.operators:
            try:
                sealed.append(builder.register(item.definition))
            except OperatorRegistryError as exc:
                raise DataSchemaInterfaceError(str(exc)) from exc
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
        missing = REQUIRED_DATA_SCHEMA_INTERFACE_FAMILIES - present
        if missing:
            raise DataSchemaInterfaceCoverageError(
                "data/schema/interface catalogue missing required families: "
                + ", ".join(sorted(missing))
            )
        missing_classes = ADMITTED_OPERATOR_CLASSES - set(self.operator_classes())
        if missing_classes:
            raise DataSchemaInterfaceCoverageError(
                "data/schema/interface catalogue missing required operator "
                "classes: " + ", ".join(sorted(missing_classes))
            )
        # Domain subsets: data families and interface families must both appear.
        if not (REQUIRED_DATA_SCHEMA_FAMILIES <= present):
            raise DataSchemaInterfaceCoverageError(
                "data/schema families incomplete: missing "
                + ", ".join(sorted(REQUIRED_DATA_SCHEMA_FAMILIES - present))
            )
        if not (REQUIRED_INTERFACE_CONTRACT_FAMILIES <= present):
            raise DataSchemaInterfaceCoverageError(
                "interface-contract families incomplete: missing "
                + ", ".join(sorted(REQUIRED_INTERFACE_CONTRACT_FAMILIES - present))
            )


def build_data_schema_interface_operators(
    specs: Iterable[DataSchemaInterfaceOperatorSpec] | None = None,
    *,
    producer_id: str = DATA_SCHEMA_INTERFACE_OPERATORS_PRODUCER,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DataSchemaInterfaceMutationOperators:
    """Build a sealed catalogue from specs (defaults: normative full set).

    The sealed ``DataSchemaInterfaceMutationOperators@1`` interface always
    requires complete family and class coverage; incomplete assemblies fail
    closed.
    """

    recipe_list = (
        list(data_schema_interface_operator_specs())
        if specs is None
        else list(specs)
    )
    if not recipe_list:
        raise DataSchemaInterfaceError(
            "data/schema/interface catalogue requires at least one operator spec"
        )
    handles: list[DataSchemaInterfaceOperator] = []
    for spec in recipe_list:
        if not isinstance(spec, DataSchemaInterfaceOperatorSpec):
            raise DataSchemaInterfaceError(
                "specs entries must be DataSchemaInterfaceOperatorSpec"
            )
        definition = build_data_schema_interface_operator(spec)
        handles.append(
            DataSchemaInterfaceOperator(
                _definition=definition,
                family=spec.family,
                spec_operator_id=spec.operator_id,
            )
        )
    catalogue = DataSchemaInterfaceMutationOperators(
        operators=handles,
        producer_id=producer_id,
        notes=notes
        if notes is not None
        else (
            "Normative data/schema and interface-contract mutation operators "
            "with structured transforms only (AAE-016)"
        ),
        metadata=metadata or {"task_id": "AAE-016"},
    )
    catalogue.assert_complete_coverage()
    return catalogue


def default_data_schema_interface_operators() -> DataSchemaInterfaceMutationOperators:
    """Return the normative sealed catalogue (stable identity across calls)."""

    return build_data_schema_interface_operators()


def data_schema_interface_operator_definitions() -> tuple[
    MutationOperatorDefinition, ...
]:
    """Convenience: sealed definitions only, deterministic order."""

    return default_data_schema_interface_operators().definitions()


def data_schema_interface_families_covered() -> frozenset[str]:
    """Return the family set covered by the normative catalogue."""

    return frozenset(default_data_schema_interface_operators().families())


__all__ = [
    "ADMITTED_OPERATOR_CLASSES",
    "DATA_SCHEMA_INTERFACE_OPERATORS_INTERFACE",
    "DATA_SCHEMA_INTERFACE_OPERATORS_PRODUCER",
    "DATA_SCHEMA_INTERFACE_OPERATORS_SCHEMA",
    "DATA_SCHEMA_INTERFACE_OPERATORS_VERSION",
    "DATA_SCHEMA_INTERFACE_OPERATOR_VERSION",
    "DEFAULT_DATA_SCHEMA_RISK_CLASS",
    "DEFAULT_INTERFACE_RISK_CLASS",
    "DataSchemaInterfaceCoverageError",
    "DataSchemaInterfaceError",
    "DataSchemaInterfaceFamily",
    "DataSchemaInterfaceMutationOperators",
    "DataSchemaInterfaceOperator",
    "DataSchemaInterfaceOperatorSpec",
    "DataSchemaInterfaceTextEditError",
    "REQUIRED_DATA_SCHEMA_FAMILIES",
    "REQUIRED_DATA_SCHEMA_INTERFACE_FAMILIES",
    "REQUIRED_INTERFACE_CONTRACT_FAMILIES",
    "assert_data_schema_interface_operator_defaults",
    "assert_structured_transformation",
    "build_data_schema_interface_operator",
    "build_data_schema_interface_operators",
    "data_schema_interface_families_covered",
    "data_schema_interface_operator_definitions",
    "data_schema_interface_operator_specs",
    "default_data_schema_interface_operators",
]
