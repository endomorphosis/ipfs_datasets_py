"""State-machine, distributed-system, storage, and durability operators (AAE-019).

Interface: ``DistributedStorageMutationOperators@1``

Sealed, bounded, deterministic operator catalogue covering both the
``state_distributed`` and ``storage_durability`` operator classes. Coverage is
normative and complete for the plan's state/distributed and storage/durability
families:

State / distributed families
    illegal and skipped transitions; CAS; fencing; leases; ownership;
    idempotency; partial mutation; compensation; convergence; proof forests;
    parent seals

Storage / durability families
    pre-commit acknowledgement; directory sync; checksum; stale reads;
    read-back; corruption replacement; queued-as-committed; provider-ack;
    durable-commit distinctions (sync vs checksum vs read-back)

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

DISTRIBUTED_STORAGE_OPERATORS_INTERFACE: Final[str] = (
    "DistributedStorageMutationOperators@1"
)
DISTRIBUTED_STORAGE_OPERATORS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-"
    "distributed-storage-mutation-operators@1"
)
DISTRIBUTED_STORAGE_OPERATORS_VERSION: Final[str] = "1"
DISTRIBUTED_STORAGE_OPERATORS_PRODUCER: Final[str] = (
    "adversarial-assurance.distributed-storage-mutation-operators@1"
)
DISTRIBUTED_STORAGE_OPERATOR_VERSION: Final[str] = "1"

_DEFAULT_MAX_FILES: Final[int] = 1
_DEFAULT_MAX_SYMBOLS: Final[int] = 2
_DEFAULT_MAX_SPAN_LINES: Final[int] = 64
_DEFAULT_MAX_MUTANTS_PER_TARGET: Final[int] = 6

DEFAULT_STATE_DISTRIBUTED_RISK_CLASS: Final[str] = (
    MutationRiskClass.DISTRIBUTED_TRANSITION.value
)
DEFAULT_STORAGE_DURABILITY_RISK_CLASS: Final[str] = MutationRiskClass.DURABILITY.value

_DEFAULT_LANGUAGES: Final[tuple[str, ...]] = ("python", "typescript")
_DEFAULT_ARTIFACT_TYPES: Final[tuple[str, ...]] = ("source_module",)
_DEFAULT_PREREQUISITES: Final[tuple[str, ...]] = (
    "parsed_ast",
    "symbol_table",
)

# Metadata keys for family / class binding (avoid private-field markers).
_FAMILY_METADATA_KEY: Final[str] = "ds_family"
_OPERATOR_CLASS_METADATA_KEY: Final[str] = "ds_operator_class"
# Distinguishes durable-commit observation modes when relevant.
_DURABILITY_DISTINCTION_KEY: Final[str] = "durability_distinction"

ADMITTED_OPERATOR_CLASSES: Final[frozenset[str]] = frozenset(
    {
        OperatorClass.STATE_DISTRIBUTED.value,
        OperatorClass.STORAGE_DURABILITY.value,
    }
)

# Closed durability observation distinctions (storage class).
DURABILITY_DISTINCTIONS: Final[frozenset[str]] = frozenset(
    {
        "durable_commit",
        "directory_sync",
        "checksum",
        "read_back",
        "provider_ack",
        "pre_commit_ack",
        "queued_as_committed",
        "stale_read",
        "corruption_replacement",
    }
)


class DistributedStorageError(AssuranceBaseError):
    """Raised when a distributed/storage operator contract fails closed."""


class DistributedStorageCoverageError(DistributedStorageError):
    """Raised when the catalogue does not cover a required family or class."""


class DistributedStorageFamily(str, Enum):
    """Closed family keys required by plan acceptance for AAE-019."""

    # State / distributed
    ILLEGAL_TRANSITION = "illegal_transition"
    SKIPPED_TRANSITION = "skipped_transition"
    CAS = "cas"
    FENCING = "fencing"
    LEASE = "lease"
    OWNERSHIP = "ownership"
    IDEMPOTENCY = "idempotency"
    PARTIAL_MUTATION = "partial_mutation"
    COMPENSATION = "compensation"
    CONVERGENCE = "convergence"
    PROOF_FOREST = "proof_forest"
    PARENT_SEALS = "parent_seals"
    # Storage / durability
    PRE_COMMIT_ACK = "pre_commit_ack"
    DIRECTORY_SYNC = "directory_sync"
    CHECKSUM = "checksum"
    STALE_READ = "stale_read"
    READ_BACK = "read_back"
    CORRUPTION_REPLACEMENT = "corruption_replacement"
    QUEUED_AS_COMMITTED = "queued_as_committed"
    PROVIDER_ACK = "provider_ack"
    DURABLE_COMMIT = "durable_commit"


REQUIRED_DISTRIBUTED_STORAGE_FAMILIES: Final[frozenset[str]] = frozenset(
    item.value for item in DistributedStorageFamily
)

REQUIRED_STATE_DISTRIBUTED_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        DistributedStorageFamily.ILLEGAL_TRANSITION.value,
        DistributedStorageFamily.SKIPPED_TRANSITION.value,
        DistributedStorageFamily.CAS.value,
        DistributedStorageFamily.FENCING.value,
        DistributedStorageFamily.LEASE.value,
        DistributedStorageFamily.OWNERSHIP.value,
        DistributedStorageFamily.IDEMPOTENCY.value,
        DistributedStorageFamily.PARTIAL_MUTATION.value,
        DistributedStorageFamily.COMPENSATION.value,
        DistributedStorageFamily.CONVERGENCE.value,
        DistributedStorageFamily.PROOF_FOREST.value,
        DistributedStorageFamily.PARENT_SEALS.value,
    }
)

REQUIRED_STORAGE_DURABILITY_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        DistributedStorageFamily.PRE_COMMIT_ACK.value,
        DistributedStorageFamily.DIRECTORY_SYNC.value,
        DistributedStorageFamily.CHECKSUM.value,
        DistributedStorageFamily.STALE_READ.value,
        DistributedStorageFamily.READ_BACK.value,
        DistributedStorageFamily.CORRUPTION_REPLACEMENT.value,
        DistributedStorageFamily.QUEUED_AS_COMMITTED.value,
        DistributedStorageFamily.PROVIDER_ACK.value,
        DistributedStorageFamily.DURABLE_COMMIT.value,
    }
)

_STATE_DISTRIBUTED_ONLY_FAMILIES: Final[frozenset[str]] = (
    REQUIRED_STATE_DISTRIBUTED_FAMILIES
)
_STORAGE_DURABILITY_ONLY_FAMILIES: Final[frozenset[str]] = (
    REQUIRED_STORAGE_DURABILITY_FAMILIES
)

# Map storage families to their durability observation distinction token.
_FAMILY_TO_DURABILITY_DISTINCTION: Final[Mapping[str, str]] = MappingProxyType(
    {
        DistributedStorageFamily.PRE_COMMIT_ACK.value: "pre_commit_ack",
        DistributedStorageFamily.DIRECTORY_SYNC.value: "directory_sync",
        DistributedStorageFamily.CHECKSUM.value: "checksum",
        DistributedStorageFamily.STALE_READ.value: "stale_read",
        DistributedStorageFamily.READ_BACK.value: "read_back",
        DistributedStorageFamily.CORRUPTION_REPLACEMENT.value: (
            "corruption_replacement"
        ),
        DistributedStorageFamily.QUEUED_AS_COMMITTED.value: "queued_as_committed",
        DistributedStorageFamily.PROVIDER_ACK.value: "provider_ack",
        DistributedStorageFamily.DURABLE_COMMIT.value: "durable_commit",
    }
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
            raise DistributedStorageError(
                f"unsupported operator_class: {value!r}"
            ) from exc
    else:
        raise DistributedStorageError(
            "operator_class must be OperatorClass or str"
        )
    if class_value not in ADMITTED_OPERATOR_CLASSES:
        raise DistributedStorageError(
            "operator_class must be state_distributed or storage_durability; "
            f"got {class_value!r}"
        )
    return class_value


def _default_operator_class_for_family(family: str) -> str:
    if family in _STATE_DISTRIBUTED_ONLY_FAMILIES:
        return OperatorClass.STATE_DISTRIBUTED.value
    if family in _STORAGE_DURABILITY_ONLY_FAMILIES:
        return OperatorClass.STORAGE_DURABILITY.value
    raise DistributedStorageError(
        f"unsupported family for class default: {family!r}"
    )


def _default_risk_for_class(operator_class: str) -> str:
    if operator_class == OperatorClass.STATE_DISTRIBUTED.value:
        return DEFAULT_STATE_DISTRIBUTED_RISK_CLASS
    return DEFAULT_STORAGE_DURABILITY_RISK_CLASS


@dataclass(frozen=True, slots=True)
class DistributedStorageOperatorSpec:
    """Declarative recipe for one sealed state/distributed or storage operator.

    Specs are pure data used to construct ``MutationOperatorDefinition``
    values. They are not durable CAS records.
    """

    operator_id: str
    family: DistributedStorageFamily | str
    semantic_intent: str
    syntactic_transformation: str
    expected_violated_property_classes: Sequence[PropertyClass | str]
    likely_equivalent_conditions: Sequence[str] = ()
    operator_class: OperatorClass | str | None = None
    risk_class: MutationRiskClass | str | None = None
    durability_distinction: str | None = None
    max_mutants_per_target: int = _DEFAULT_MAX_MUTANTS_PER_TARGET
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.operator_id) is not str or not self.operator_id.strip():
            raise DistributedStorageError("operator_id must be a nonempty string")

        family = self.family
        if isinstance(family, DistributedStorageFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = DistributedStorageFamily(family).value
            except ValueError as exc:
                raise DistributedStorageError(
                    f"unsupported state/distributed or storage family: {family!r}"
                ) from exc
        else:
            raise DistributedStorageError(
                "family must be DistributedStorageFamily or str"
            )
        object.__setattr__(self, "family", family_value)

        if self.operator_class is None:
            class_value = _default_operator_class_for_family(family_value)
        else:
            class_value = _normalize_operator_class(self.operator_class)
        if family_value in _STATE_DISTRIBUTED_ONLY_FAMILIES and (
            class_value != OperatorClass.STATE_DISTRIBUTED.value
        ):
            raise DistributedStorageError(
                f"family {family_value!r} requires operator_class state_distributed"
            )
        if family_value in _STORAGE_DURABILITY_ONLY_FAMILIES and (
            class_value != OperatorClass.STORAGE_DURABILITY.value
        ):
            raise DistributedStorageError(
                f"family {family_value!r} requires operator_class storage_durability"
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
                    raise DistributedStorageError(
                        f"unsupported risk_class: {risk!r}"
                    ) from exc
            else:
                raise DistributedStorageError(
                    "risk_class must be MutationRiskClass or str"
                )
        object.__setattr__(self, "risk_class", risk_value)

        # Durability distinction: required for storage families, forbidden for
        # state/distributed families unless explicitly matching a known token.
        distinction = self.durability_distinction
        expected_distinction = _FAMILY_TO_DURABILITY_DISTINCTION.get(family_value)
        if class_value == OperatorClass.STORAGE_DURABILITY.value:
            if distinction is None:
                distinction = expected_distinction
            if type(distinction) is not str or not distinction.strip():
                raise DistributedStorageError(
                    "storage_durability operators require durability_distinction"
                )
            if distinction not in DURABILITY_DISTINCTIONS:
                raise DistributedStorageError(
                    f"unsupported durability_distinction: {distinction!r}"
                )
            if (
                expected_distinction is not None
                and distinction != expected_distinction
            ):
                raise DistributedStorageError(
                    f"family {family_value!r} requires durability_distinction "
                    f"{expected_distinction!r}, got {distinction!r}"
                )
        else:
            if distinction is not None:
                raise DistributedStorageError(
                    "state_distributed operators must not set "
                    "durability_distinction; that distinction is storage-only"
                )
        object.__setattr__(self, "durability_distinction", distinction)

        if type(self.semantic_intent) is not str or not self.semantic_intent.strip():
            raise DistributedStorageError("semantic_intent must be nonempty")
        if (
            type(self.syntactic_transformation) is not str
            or not self.syntactic_transformation.strip()
        ):
            raise DistributedStorageError(
                "syntactic_transformation must be nonempty"
            )

        props = tuple(self.expected_violated_property_classes)
        if not props:
            raise DistributedStorageError(
                "expected_violated_property_classes must not be empty"
            )
        object.__setattr__(self, "expected_violated_property_classes", props)

        equiv = tuple(self.likely_equivalent_conditions or ())
        if not equiv:
            raise DistributedStorageError(
                "likely_equivalent_conditions must provide equivalence hints"
            )
        for condition in equiv:
            if type(condition) is not str or not condition.strip():
                raise DistributedStorageError(
                    "likely_equivalent_conditions entries must be nonempty strings"
                )
        object.__setattr__(self, "likely_equivalent_conditions", equiv)

        if (
            type(self.max_mutants_per_target) is not int
            or isinstance(self.max_mutants_per_target, bool)
            or self.max_mutants_per_target < 1
        ):
            raise DistributedStorageError(
                "max_mutants_per_target must be a positive integer"
            )

        meta = dict(self.metadata or {})
        meta.setdefault(_FAMILY_METADATA_KEY, family_value)
        meta.setdefault(_OPERATOR_CLASS_METADATA_KEY, class_value)
        if distinction is not None:
            meta.setdefault(_DURABILITY_DISTINCTION_KEY, distinction)
        try:
            reject_private_model_authority_and_host_fallbacks(
                meta, path="DistributedStorageOperatorSpec.metadata"
            )
            cid_for_structured(meta)
        except Exception as exc:  # noqa: BLE001
            raise DistributedStorageError(
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


def assert_distributed_storage_operator_defaults(
    operator: MutationOperatorDefinition,
) -> None:
    """Fail closed when an operator lacks class, intent, or property defaults."""

    if not isinstance(operator, MutationOperatorDefinition):
        raise DistributedStorageError(
            "operator must be a sealed MutationOperatorDefinition"
        )
    if operator.operator_class not in ADMITTED_OPERATOR_CLASSES:
        raise DistributedStorageError(
            "operator_class must be state_distributed or storage_durability"
        )
    if not operator.semantic_intent or not str(operator.semantic_intent).strip():
        raise DistributedStorageError(
            f"operator {operator.operator_id} must declare semantic_intent"
        )
    if not operator.likely_equivalent_conditions:
        raise DistributedStorageError(
            f"operator {operator.operator_id} must declare equivalence hints "
            "(likely_equivalent_conditions)"
        )

    props = set(operator.expected_violated_property_classes)
    if operator.operator_class == OperatorClass.STATE_DISTRIBUTED.value:
        allowed = {
            PropertyClass.STATE_TRANSITION.value,
            PropertyClass.IDEMPOTENCY.value,
            PropertyClass.COMPENSATION.value,
            PropertyClass.DATA_INTEGRITY.value,
            PropertyClass.DURABILITY.value,
            PropertyClass.PROOF_ADEQUACY.value,
            PropertyClass.RECEIPT_AUTHENTICITY.value,
            PropertyClass.SIDE_EFFECT_OBLIGATION.value,
        }
        if not (props & allowed):
            raise DistributedStorageError(
                f"operator {operator.operator_id} must expect a state/"
                "distributed-related property violation "
                f"(one of {sorted(allowed)})"
            )
        if PropertyClass.STATE_TRANSITION.value not in props:
            # Non-transition distributed mutants still violate transition safety
            # unless they exclusively target idempotency, compensation, or proof.
            if not (
                props
                & {
                    PropertyClass.IDEMPOTENCY.value,
                    PropertyClass.COMPENSATION.value,
                    PropertyClass.PROOF_ADEQUACY.value,
                    PropertyClass.RECEIPT_AUTHENTICITY.value,
                }
            ):
                raise DistributedStorageError(
                    f"operator {operator.operator_id} must expect "
                    "state_transition, idempotency, compensation, proof_adequacy, "
                    "or receipt_authenticity property violations"
                )
    else:
        allowed = {
            PropertyClass.DURABILITY.value,
            PropertyClass.STORAGE_INTEGRITY.value,
            PropertyClass.DATA_INTEGRITY.value,
            PropertyClass.SIDE_EFFECT_OBLIGATION.value,
            PropertyClass.IDEMPOTENCY.value,
        }
        if not (props & allowed):
            raise DistributedStorageError(
                f"operator {operator.operator_id} must expect a storage/"
                "durability-related property violation "
                f"(one of {sorted(allowed)})"
            )
        if PropertyClass.DURABILITY.value not in props and (
            PropertyClass.STORAGE_INTEGRITY.value not in props
        ):
            raise DistributedStorageError(
                f"operator {operator.operator_id} must expect durability or "
                "storage_integrity property violations"
            )
        distinction = operator.metadata.get(_DURABILITY_DISTINCTION_KEY)
        if distinction is not None and distinction not in DURABILITY_DISTINCTIONS:
            raise DistributedStorageError(
                f"operator {operator.operator_id} has unsupported "
                f"durability_distinction {distinction!r}"
            )


def build_distributed_storage_operator(
    spec: DistributedStorageOperatorSpec,
    *,
    supported_languages: Sequence[str] | None = None,
    supported_artifact_types: Sequence[str] | None = None,
    target_prerequisites: Sequence[str] | None = None,
    scope_limits: ScopeLimits | None = None,
    rollback: RollbackDeclaration | None = None,
    required_sandbox: SandboxRequirement | None = None,
    operator_version: str = DISTRIBUTED_STORAGE_OPERATOR_VERSION,
) -> MutationOperatorDefinition:
    """Seal one state/distributed or storage/durability operator under defaults."""

    if not isinstance(spec, DistributedStorageOperatorSpec):
        raise DistributedStorageError(
            "spec must be a DistributedStorageOperatorSpec"
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
        raise DistributedStorageError(str(exc)) from exc
    assert_distributed_storage_operator_defaults(sealed)
    return sealed


# ---------------------------------------------------------------------------
# Normative catalogue recipes (plan acceptance families)
# ---------------------------------------------------------------------------


def distributed_storage_operator_specs() -> (
    tuple[DistributedStorageOperatorSpec, ...]
):
    """Return the closed, ordered set of normative operator recipes."""

    state_tr = PropertyClass.STATE_TRANSITION
    idempotency = PropertyClass.IDEMPOTENCY
    compensation = PropertyClass.COMPENSATION
    data_int = PropertyClass.DATA_INTEGRITY
    durability = PropertyClass.DURABILITY
    storage_int = PropertyClass.STORAGE_INTEGRITY
    proof_adeq = PropertyClass.PROOF_ADEQUACY
    receipt = PropertyClass.RECEIPT_AUTHENTICITY
    obligation = PropertyClass.SIDE_EFFECT_OBLIGATION

    return (
        # --- illegal / skipped transitions -----------------------------------
        DistributedStorageOperatorSpec(
            operator_id="sd_illegal_state_transition",
            family=DistributedStorageFamily.ILLEGAL_TRANSITION,
            semantic_intent=(
                "Force a state-machine edge that is not in the legal transition "
                "relation so the system enters an unreachable or forbidden state"
            ),
            syntactic_transformation="replace_transition_target_with_illegal_state",
            expected_violated_property_classes=(state_tr,),
            likely_equivalent_conditions=(
                "target_state_is_already_reachable_via_legal_path",
                "transition_table_treats_edge_as_legal",
            ),
            notes="Illegal state-machine transition",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_skip_required_transition",
            family=DistributedStorageFamily.SKIPPED_TRANSITION,
            semantic_intent=(
                "Skip a required intermediate transition so the machine advances "
                "past a gate that must observe prior state"
            ),
            syntactic_transformation="elide_required_intermediate_transition",
            expected_violated_property_classes=(state_tr,),
            likely_equivalent_conditions=(
                "skipped_state_has_no_observers",
                "elided_transition_is_a_no_op_by_contract",
            ),
            notes="Skipped required transition",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_bypass_transition_guard",
            family=DistributedStorageFamily.ILLEGAL_TRANSITION,
            semantic_intent=(
                "Bypass a transition guard or precondition so a state change "
                "occurs without the required enabling condition"
            ),
            syntactic_transformation="replace_transition_guard_with_true",
            expected_violated_property_classes=(state_tr, data_int),
            likely_equivalent_conditions=(
                "guard_is_always_true_in_deployment",
                "precondition_is_enforced_at_a_stronger_boundary",
            ),
            notes="Bypass transition guard",
        ),
        # --- CAS -------------------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="sd_cas_ignore_expected_old",
            family=DistributedStorageFamily.CAS,
            semantic_intent=(
                "Ignore the expected-old value in a compare-and-swap so a write "
                "succeeds even when the observed head has changed"
            ),
            syntactic_transformation="drop_expected_old_check_from_cas",
            expected_violated_property_classes=(state_tr, data_int, durability),
            likely_equivalent_conditions=(
                "head_never_changes_concurrently",
                "cas_is_advisory_only_by_contract",
            ),
            notes="CAS without expected-old check",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_cas_accept_stale_head",
            family=DistributedStorageFamily.CAS,
            semantic_intent=(
                "Accept a stale CAS head as current so a concurrent writer "
                "overwrites a newer committed revision"
            ),
            syntactic_transformation="treat_stale_cas_head_as_current",
            expected_violated_property_classes=(state_tr, data_int),
            likely_equivalent_conditions=(
                "only_one_writer_exists",
                "stale_head_equals_current_head",
            ),
            notes="CAS accepts stale head",
        ),
        # --- fencing ---------------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="sd_accept_stale_fencing_token",
            family=DistributedStorageFamily.FENCING,
            semantic_intent=(
                "Accept a stale fencing token so a demoted or superseded "
                "leader can still mutate protected state"
            ),
            syntactic_transformation="skip_fencing_token_generation_check",
            expected_violated_property_classes=(state_tr, data_int),
            likely_equivalent_conditions=(
                "fencing_token_never_increments",
                "only_one_leader_ever_exists",
            ),
            notes="Stale fencing token accepted",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_omit_fencing_on_mutation",
            family=DistributedStorageFamily.FENCING,
            semantic_intent=(
                "Omit fencing-token validation on a mutation path that must "
                "reject writes from fenced-out owners"
            ),
            syntactic_transformation="remove_fencing_token_validation",
            expected_violated_property_classes=(state_tr,),
            likely_equivalent_conditions=(
                "mutations_are_read_only",
                "fencing_enforced_by_storage_layer",
            ),
            notes="Omit fencing validation on mutation",
        ),
        # --- leases ----------------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="sd_ignore_lease_expiry",
            family=DistributedStorageFamily.LEASE,
            semantic_intent=(
                "Ignore lease expiry so a holder continues to act after the "
                "lease has expired and another owner may have acquired it"
            ),
            syntactic_transformation="skip_lease_expiry_check",
            expected_violated_property_classes=(state_tr,),
            likely_equivalent_conditions=(
                "leases_never_expire_in_practice",
                "expiry_is_checked_on_every_storage_call",
            ),
            notes="Ignore lease expiry",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_extend_lease_without_authority",
            family=DistributedStorageFamily.LEASE,
            semantic_intent=(
                "Extend or renew a lease without proving current ownership or "
                "fencing authority"
            ),
            syntactic_transformation="renew_lease_without_ownership_proof",
            expected_violated_property_classes=(state_tr, data_int),
            likely_equivalent_conditions=(
                "renewal_is_open_to_any_caller_by_design",
                "storage_rejects_unproven_renewal",
            ),
            notes="Lease renewal without ownership proof",
        ),
        # --- ownership -------------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="sd_mutate_without_ownership",
            family=DistributedStorageFamily.OWNERSHIP,
            semantic_intent=(
                "Allow a mutation of owned distributed state without verifying "
                "current ownership claims"
            ),
            syntactic_transformation="skip_ownership_claim_check_before_mutation",
            expected_violated_property_classes=(state_tr, data_int),
            likely_equivalent_conditions=(
                "resource_is_unowned_by_design",
                "ownership_is_enforced_by_lease_layer",
            ),
            notes="Mutation without ownership check",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_transfer_ownership_without_quorum",
            family=DistributedStorageFamily.OWNERSHIP,
            semantic_intent=(
                "Transfer ownership without the required quorum, fencing, or "
                "CAS of the ownership record"
            ),
            syntactic_transformation="transfer_ownership_without_quorum_or_cas",
            expected_violated_property_classes=(state_tr,),
            likely_equivalent_conditions=(
                "single_node_deployment_has_no_quorum",
                "ownership_record_is_append_only_elsewhere",
            ),
            notes="Ownership transfer without quorum/CAS",
        ),
        # --- idempotency -----------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="sd_drop_idempotency_key",
            family=DistributedStorageFamily.IDEMPOTENCY,
            semantic_intent=(
                "Drop or ignore an operation idempotency key so a retry applies "
                "a non-idempotent distributed mutation twice"
            ),
            syntactic_transformation="remove_idempotency_key_from_operation",
            expected_violated_property_classes=(idempotency, state_tr),
            likely_equivalent_conditions=(
                "operation_is_fully_idempotent_by_content",
                "retries_never_occur",
            ),
            notes="Drop operation idempotency key",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_reuse_idempotency_key_for_new_op",
            family=DistributedStorageFamily.IDEMPOTENCY,
            semantic_intent=(
                "Reuse a prior idempotency key for a new logical operation so "
                "deduplication maps distinct work to a stale result"
            ),
            syntactic_transformation="reuse_stale_idempotency_key_for_new_operation",
            expected_violated_property_classes=(idempotency, data_int),
            likely_equivalent_conditions=(
                "new_operation_is_semantically_identical",
                "key_namespace_isolates_operations",
            ),
            notes="Reuse idempotency key for new operation",
        ),
        # --- partial mutation ------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="sd_commit_partial_replica_set",
            family=DistributedStorageFamily.PARTIAL_MUTATION,
            semantic_intent=(
                "Treat a partially replicated mutation as fully committed so "
                "some replicas remain on the prior state"
            ),
            syntactic_transformation="mark_partial_replica_write_as_committed",
            expected_violated_property_classes=(state_tr, durability, data_int),
            likely_equivalent_conditions=(
                "single_replica_deployment",
                "partial_set_equals_full_quorum",
            ),
            notes="Partial replica set marked committed",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_skip_second_phase_write",
            family=DistributedStorageFamily.PARTIAL_MUTATION,
            semantic_intent=(
                "Skip the second phase of a multi-phase distributed write so "
                "only a subset of intended mutations is durable"
            ),
            syntactic_transformation="omit_second_phase_distributed_write",
            expected_violated_property_classes=(state_tr, durability),
            likely_equivalent_conditions=(
                "second_phase_is_empty_by_contract",
                "first_phase_is_already_complete_and_sufficient",
            ),
            notes="Skip second-phase distributed write",
        ),
        # --- compensation ----------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="sd_skip_distributed_compensation",
            family=DistributedStorageFamily.COMPENSATION,
            semantic_intent=(
                "Skip distributed compensation after a partial multi-node "
                "mutation so unreverted effects remain on remote participants"
            ),
            syntactic_transformation="omit_distributed_compensation_on_partial_failure",
            expected_violated_property_classes=(compensation, state_tr),
            likely_equivalent_conditions=(
                "partial_failure_never_occurs",
                "remote_effects_are_already_no_ops",
            ),
            notes="Skip distributed compensation",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_incomplete_distributed_compensation",
            family=DistributedStorageFamily.COMPENSATION,
            semantic_intent=(
                "Run compensation against only a subset of participants so some "
                "nodes retain unreverted distributed effects"
            ),
            syntactic_transformation="compensate_only_subset_of_participants",
            expected_violated_property_classes=(compensation, data_int),
            likely_equivalent_conditions=(
                "omitted_participants_had_no_effects",
                "participants_self_heal_identically",
            ),
            notes="Incomplete distributed compensation",
        ),
        # --- convergence -----------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="sd_declare_convergence_early",
            family=DistributedStorageFamily.CONVERGENCE,
            semantic_intent=(
                "Declare distributed convergence before all replicas have "
                "applied the same committed state"
            ),
            syntactic_transformation="return_converged_before_replica_agreement",
            expected_violated_property_classes=(state_tr, data_int),
            likely_equivalent_conditions=(
                "single_replica_always_agrees_with_itself",
                "convergence_is_eventual_and_unchecked",
            ),
            notes="Early convergence declaration",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_ignore_divergent_replica",
            family=DistributedStorageFamily.CONVERGENCE,
            semantic_intent=(
                "Ignore a divergent replica observation so the system claims "
                "agreement while at least one replica differs"
            ),
            syntactic_transformation="drop_divergent_replica_from_agreement_set",
            expected_violated_property_classes=(state_tr, data_int),
            likely_equivalent_conditions=(
                "divergent_replica_is_marked_out_of_service",
                "agreement_set_is_explicitly_majority_only",
            ),
            notes="Ignore divergent replica",
        ),
        # --- proof forests ---------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="sd_drop_proof_forest_node",
            family=DistributedStorageFamily.PROOF_FOREST,
            semantic_intent=(
                "Drop a required node from a temporary proof forest so completeness "
                "is claimed without covering all dependent obligations"
            ),
            syntactic_transformation="remove_required_node_from_proof_forest",
            expected_violated_property_classes=(proof_adeq, receipt),
            likely_equivalent_conditions=(
                "dropped_node_is_optional",
                "obligation_covered_by_stronger_sibling",
            ),
            notes="Drop proof-forest node",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_reuse_stale_proof_forest",
            family=DistributedStorageFamily.PROOF_FOREST,
            semantic_intent=(
                "Reuse a stale proof forest for a new mutant or revision so "
                "verification appears complete against outdated evidence"
            ),
            syntactic_transformation="reattach_stale_proof_forest_to_new_revision",
            expected_violated_property_classes=(proof_adeq, receipt, state_tr),
            likely_equivalent_conditions=(
                "forest_root_matches_current_revision",
                "forest_is_empty_and_no_proofs_required",
            ),
            notes="Reuse stale proof forest",
        ),
        # --- parent seals ----------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="sd_omit_parent_seal_link",
            family=DistributedStorageFamily.PARENT_SEALS,
            semantic_intent=(
                "Omit a required parent seal link so a child seal or receipt "
                "claims ancestry without binding the parent identity"
            ),
            syntactic_transformation="clear_parent_seal_cid_from_child_receipt",
            expected_violated_property_classes=(receipt, proof_adeq, state_tr),
            likely_equivalent_conditions=(
                "seal_is_a_root_with_no_parent",
                "parent_link_is_reconstructed_from_chain_elsewhere",
            ),
            notes="Omit parent seal link",
        ),
        DistributedStorageOperatorSpec(
            operator_id="sd_bind_wrong_parent_seal",
            family=DistributedStorageFamily.PARENT_SEALS,
            semantic_intent=(
                "Bind a child seal to the wrong parent seal CID so lineage "
                "verification accepts an incorrect ancestry"
            ),
            syntactic_transformation="replace_parent_seal_cid_with_unrelated_seal",
            expected_violated_property_classes=(receipt, proof_adeq),
            likely_equivalent_conditions=(
                "wrong_parent_is_semantically_identical",
                "lineage_is_not_checked_by_policy",
            ),
            notes="Wrong parent seal binding",
        ),
        # --- pre-commit acknowledgement --------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="st_ack_before_durable_commit",
            family=DistributedStorageFamily.PRE_COMMIT_ACK,
            semantic_intent=(
                "Acknowledge success before durable commit so callers treat "
                "volatile or journaled state as committed"
            ),
            syntactic_transformation="return_ack_before_durable_commit",
            expected_violated_property_classes=(durability, obligation),
            likely_equivalent_conditions=(
                "ack_is_explicitly_at_least_once_pre_commit",
                "commit_is_synchronous_and_already_durable",
            ),
            notes="Ack before durable commit (pre-commit distinction)",
        ),
        DistributedStorageOperatorSpec(
            operator_id="st_treat_journal_write_as_commit",
            family=DistributedStorageFamily.PRE_COMMIT_ACK,
            semantic_intent=(
                "Treat a journal or WAL append as a durable commit without "
                "sync or commit barrier"
            ),
            syntactic_transformation="map_journal_append_to_committed_status",
            expected_violated_property_classes=(durability, storage_int),
            likely_equivalent_conditions=(
                "journal_is_synchronous_and_fsynced",
                "crash_recovery_replays_to_identical_state",
            ),
            notes="Journal append treated as commit",
        ),
        # --- directory sync --------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="st_skip_directory_sync",
            family=DistributedStorageFamily.DIRECTORY_SYNC,
            semantic_intent=(
                "Skip directory fsync/sync after a rename or create so name "
                "durability is claimed without a directory barrier"
            ),
            syntactic_transformation="omit_directory_fsync_after_rename_or_create",
            expected_violated_property_classes=(durability, storage_int),
            likely_equivalent_conditions=(
                "filesystem_guarantees_directory_atomicity",
                "parent_directory_is_already_synced",
            ),
            notes="Skip directory sync (sync distinction)",
        ),
        DistributedStorageOperatorSpec(
            operator_id="st_sync_file_not_directory",
            family=DistributedStorageFamily.DIRECTORY_SYNC,
            semantic_intent=(
                "Sync only the file data and not the parent directory so "
                "directory entry durability is conflated with data sync"
            ),
            syntactic_transformation="fsync_file_only_omit_parent_directory_sync",
            expected_violated_property_classes=(durability,),
            likely_equivalent_conditions=(
                "rename_is_not_used",
                "directory_entries_are_redundant_with_file_content",
            ),
            notes="File sync without directory sync",
        ),
        # --- checksum --------------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="st_skip_checksum_verification",
            family=DistributedStorageFamily.CHECKSUM,
            semantic_intent=(
                "Skip checksum verification on read or commit so corrupt "
                "payloads are treated as durable good data"
            ),
            syntactic_transformation="bypass_storage_checksum_verification",
            expected_violated_property_classes=(storage_int, data_int, durability),
            likely_equivalent_conditions=(
                "media_never_corrupts",
                "checksum_enforced_at_outer_transport",
            ),
            notes="Skip checksum verification (checksum distinction)",
        ),
        DistributedStorageOperatorSpec(
            operator_id="st_accept_mismatched_checksum",
            family=DistributedStorageFamily.CHECKSUM,
            semantic_intent=(
                "Accept a mismatched stored checksum as success so integrity "
                "failures do not block durability claims"
            ),
            syntactic_transformation="map_checksum_mismatch_to_success",
            expected_violated_property_classes=(storage_int, data_int),
            likely_equivalent_conditions=(
                "mismatch_never_occurs",
                "degraded_mode_is_explicitly_authorized",
            ),
            notes="Accept mismatched checksum",
        ),
        # --- stale reads -----------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="st_serve_stale_read_as_current",
            family=DistributedStorageFamily.STALE_READ,
            semantic_intent=(
                "Serve a stale cached or replica read as the current durable "
                "value after a newer commit has been acknowledged"
            ),
            syntactic_transformation="return_stale_replica_or_cache_as_current",
            expected_violated_property_classes=(durability, data_int),
            likely_equivalent_conditions=(
                "no_concurrent_writers",
                "stale_value_equals_current_value",
            ),
            notes="Stale read as current",
        ),
        DistributedStorageOperatorSpec(
            operator_id="st_skip_read_your_writes",
            family=DistributedStorageFamily.STALE_READ,
            semantic_intent=(
                "Violate read-your-writes by returning a pre-commit snapshot "
                "after the same session's durable commit"
            ),
            syntactic_transformation="read_pre_commit_snapshot_after_session_write",
            expected_violated_property_classes=(durability, data_int),
            likely_equivalent_conditions=(
                "session_never_reads_after_write",
                "snapshot_isolation_is_explicit_contract",
            ),
            notes="Skip read-your-writes after commit",
        ),
        # --- read-back -------------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="st_skip_read_back_verification",
            family=DistributedStorageFamily.READ_BACK,
            semantic_intent=(
                "Skip read-back verification after write so durable commit is "
                "claimed without observing the stored bytes"
            ),
            syntactic_transformation="omit_post_write_read_back_check",
            expected_violated_property_classes=(durability, storage_int),
            likely_equivalent_conditions=(
                "storage_guarantees_read_after_write",
                "read_back_is_optional_by_contract",
            ),
            notes="Skip read-back (read-back distinction)",
        ),
        DistributedStorageOperatorSpec(
            operator_id="st_read_back_from_write_buffer",
            family=DistributedStorageFamily.READ_BACK,
            semantic_intent=(
                "Perform read-back from an in-memory write buffer instead of "
                "durable media so verification never observes storage"
            ),
            syntactic_transformation="read_back_from_write_buffer_not_media",
            expected_violated_property_classes=(durability, storage_int, data_int),
            likely_equivalent_conditions=(
                "buffer_is_identical_to_media_after_sync",
                "media_path_is_used_under_a_stronger_mode",
            ),
            notes="Read-back from write buffer not media",
        ),
        # --- corruption replacement ------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="st_replace_corrupt_with_empty",
            family=DistributedStorageFamily.CORRUPTION_REPLACEMENT,
            semantic_intent=(
                "Silently replace a corrupt durable record with empty or "
                "default content without failing closed or alerting"
            ),
            syntactic_transformation="replace_corrupt_record_with_empty_default",
            expected_violated_property_classes=(storage_int, data_int, durability),
            likely_equivalent_conditions=(
                "empty_default_is_the_authoritative_recovery_policy",
                "corruption_never_occurs",
            ),
            notes="Replace corrupt record with empty",
        ),
        DistributedStorageOperatorSpec(
            operator_id="st_accept_corrupt_as_valid",
            family=DistributedStorageFamily.CORRUPTION_REPLACEMENT,
            semantic_intent=(
                "Accept a known-corrupt block as valid storage content so "
                "integrity failures are papered over as durable success"
            ),
            syntactic_transformation="mark_corrupt_block_as_valid_content",
            expected_violated_property_classes=(storage_int, data_int),
            likely_equivalent_conditions=(
                "block_is_not_actually_corrupt",
                "higher_layer_revalidates_content",
            ),
            notes="Accept corrupt block as valid",
        ),
        # --- queued as committed ---------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="st_treat_queued_as_committed",
            family=DistributedStorageFamily.QUEUED_AS_COMMITTED,
            semantic_intent=(
                "Treat a queued or batched write as committed before the "
                "queue is flushed to durable media"
            ),
            syntactic_transformation="map_enqueued_write_to_committed_status",
            expected_violated_property_classes=(durability, obligation),
            likely_equivalent_conditions=(
                "queue_flush_is_synchronous",
                "caller_does_not_require_commit_semantics",
            ),
            notes="Queued write treated as committed",
        ),
        DistributedStorageOperatorSpec(
            operator_id="st_success_on_queue_accept_only",
            family=DistributedStorageFamily.QUEUED_AS_COMMITTED,
            semantic_intent=(
                "Return success when the durability queue accepts a write "
                "without waiting for flush, sync, or commit confirmation"
            ),
            syntactic_transformation="return_success_on_queue_accept_without_flush",
            expected_violated_property_classes=(durability, obligation),
            likely_equivalent_conditions=(
                "queue_accept_implies_immediate_durable_flush",
                "api_documents_async_durability_only",
            ),
            notes="Success on queue accept only",
        ),
        # --- provider ack ----------------------------------------------------
        DistributedStorageOperatorSpec(
            operator_id="st_trust_provider_ack_without_verify",
            family=DistributedStorageFamily.PROVIDER_ACK,
            semantic_intent=(
                "Trust a remote storage provider acknowledgement without "
                "local checksum, read-back, or commit-token verification"
            ),
            syntactic_transformation="accept_provider_ack_without_local_verify",
            expected_violated_property_classes=(durability, storage_int),
            likely_equivalent_conditions=(
                "provider_ack_is_cryptographically_binding",
                "local_verify_is_impossible_and_policy_allows",
            ),
            notes="Trust provider ack without verify",
        ),
        DistributedStorageOperatorSpec(
            operator_id="st_conflate_provider_recv_with_durable",
            family=DistributedStorageFamily.PROVIDER_ACK,
            semantic_intent=(
                "Conflate provider receive/ack with durable commit so network "
                "acceptance is treated as media durability"
            ),
            syntactic_transformation="map_provider_recv_ack_to_durable_commit",
            expected_violated_property_classes=(durability, obligation),
            likely_equivalent_conditions=(
                "provider_recv_implies_fsync_by_sla",
                "client_only_requires_at_least_once_delivery",
            ),
            notes="Provider recv conflated with durable commit",
        ),
        # --- durable commit (explicit distinction vs sync/checksum/read-back)
        DistributedStorageOperatorSpec(
            operator_id="st_claim_commit_without_sync",
            family=DistributedStorageFamily.DURABLE_COMMIT,
            semantic_intent=(
                "Claim durable commit without a sync barrier so commit is "
                "confused with buffered write completion (distinct from "
                "checksum and read-back observations)"
            ),
            syntactic_transformation="mark_committed_without_sync_barrier",
            expected_violated_property_classes=(durability, storage_int),
            likely_equivalent_conditions=(
                "device_has_battery_backed_write_cache_with_power_fail_commit",
                "sync_is_implied_by_close_on_this_platform",
            ),
            notes="Durable commit claimed without sync",
        ),
        DistributedStorageOperatorSpec(
            operator_id="st_claim_commit_without_checksum",
            family=DistributedStorageFamily.DURABLE_COMMIT,
            semantic_intent=(
                "Claim durable commit without computing or verifying a "
                "checksum so commit is confused with unchecked persistence "
                "(distinct from sync and read-back)"
            ),
            syntactic_transformation="mark_committed_without_checksum_compute_or_verify",
            expected_violated_property_classes=(durability, storage_int, data_int),
            likely_equivalent_conditions=(
                "checksum_is_maintained_by_filesystem",
                "content_addressed_storage_implies_checksum",
            ),
            notes="Durable commit claimed without checksum",
        ),
        DistributedStorageOperatorSpec(
            operator_id="st_claim_commit_without_read_back",
            family=DistributedStorageFamily.DURABLE_COMMIT,
            semantic_intent=(
                "Claim durable commit without a read-back observation so "
                "commit is confused with unobserved write success (distinct "
                "from sync and checksum)"
            ),
            syntactic_transformation="mark_committed_without_read_back_observation",
            expected_violated_property_classes=(durability,),
            likely_equivalent_conditions=(
                "storage_api_guarantees_observed_write",
                "read_back_is_out_of_scope_for_this_api",
            ),
            notes="Durable commit claimed without read-back",
        ),
    )


# ---------------------------------------------------------------------------
# Operator handles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DistributedStorageOperator(MutationOperator):
    """Declaration-backed state/distributed or storage operator with family binding.

    Interface membership: ``DistributedStorageMutationOperators@1`` catalogue
    entry. Does not generate source rewrites; generation is owned by AAE-022.
    """

    _definition: MutationOperatorDefinition
    family: str
    spec_operator_id: str

    def __post_init__(self) -> None:
        sealed = canonicalize_operator_declaration(self._definition)
        assert_distributed_storage_operator_defaults(sealed)
        if sealed.operator_class not in ADMITTED_OPERATOR_CLASSES:
            raise DistributedStorageError(
                "DistributedStorageOperator requires operator_class "
                "state_distributed or storage_durability"
            )
        try:
            family_value = DistributedStorageFamily(self.family).value
        except ValueError as exc:
            raise DistributedStorageError(
                f"unsupported state/distributed or storage family: {self.family!r}"
            ) from exc
        meta_family = sealed.metadata.get(_FAMILY_METADATA_KEY)
        if meta_family is not None and meta_family != family_value:
            raise DistributedStorageError(
                "definition metadata ds_family does not match family binding "
                f"({meta_family!r} != {family_value!r})"
            )
        meta_class = sealed.metadata.get(_OPERATOR_CLASS_METADATA_KEY)
        if meta_class is not None and meta_class != sealed.operator_class:
            raise DistributedStorageError(
                "definition metadata ds_operator_class does not match "
                f"operator_class ({meta_class!r} != {sealed.operator_class!r})"
            )
        if family_value in _STATE_DISTRIBUTED_ONLY_FAMILIES and (
            sealed.operator_class != OperatorClass.STATE_DISTRIBUTED.value
        ):
            raise DistributedStorageError(
                f"family {family_value!r} requires operator_class state_distributed"
            )
        if family_value in _STORAGE_DURABILITY_ONLY_FAMILIES and (
            sealed.operator_class != OperatorClass.STORAGE_DURABILITY.value
        ):
            raise DistributedStorageError(
                f"family {family_value!r} requires operator_class storage_durability"
            )
        object.__setattr__(self, "_definition", sealed)
        object.__setattr__(self, "family", family_value)
        if type(self.spec_operator_id) is not str or not self.spec_operator_id:
            raise DistributedStorageError("spec_operator_id must be nonempty")
        if self.spec_operator_id != sealed.operator_id:
            raise DistributedStorageError(
                "spec_operator_id must match definition.operator_id"
            )

    @property
    def definition(self) -> MutationOperatorDefinition:
        return self._definition

    @property
    def durability_distinction(self) -> str | None:
        value = self._definition.metadata.get(_DURABILITY_DISTINCTION_KEY)
        if value is None:
            return None
        return str(value)

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
        raise DistributedStorageError(f"{name} must be a mapping")
    unknown = set(data) - fields
    if unknown:
        raise DistributedStorageError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    return dict(data)


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise DistributedStorageError(f"{name} must be a nonempty trimmed string")
    return value


@dataclass(frozen=True, slots=True)
class DistributedStorageMutationOperators:
    """Immutable catalogue of sealed state/distributed and storage operators.

    Interface: ``DistributedStorageMutationOperators@1``
    """

    operators: Sequence[DistributedStorageOperator]
    producer_id: str = DISTRIBUTED_STORAGE_OPERATORS_PRODUCER
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
            "durability_distinctions",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.operators, Sequence) or isinstance(
            self.operators, (str, bytes)
        ):
            raise DistributedStorageError(
                "operators must be a sequence of DistributedStorageOperator"
            )
        sealed: list[DistributedStorageOperator] = []
        seen_ids: set[str] = set()
        seen_cids: set[str] = set()
        families: set[str] = set()
        classes: set[str] = set()
        for item in self.operators:
            if not isinstance(item, DistributedStorageOperator):
                raise DistributedStorageError(
                    "operators entries must be DistributedStorageOperator"
                )
            definition = item.definition
            assert_distributed_storage_operator_defaults(definition)
            try:
                assert_operator_bounded(definition)
            except OperatorBoundError as exc:
                raise DistributedStorageError(str(exc)) from exc
            if definition.operator_id in seen_ids:
                raise DistributedStorageError(
                    f"duplicate operator_id in catalogue: {definition.operator_id}"
                )
            if definition.operator_cid in seen_cids:
                raise DistributedStorageError(
                    f"duplicate operator_cid in catalogue: {definition.operator_cid}"
                )
            seen_ids.add(definition.operator_id)
            seen_cids.add(definition.operator_cid)
            families.add(item.family)
            classes.add(definition.operator_class)
            sealed.append(item)

        missing = REQUIRED_DISTRIBUTED_STORAGE_FAMILIES - families
        if missing:
            raise DistributedStorageCoverageError(
                "distributed-storage catalogue missing required families: "
                + ", ".join(sorted(missing))
            )
        missing_classes = ADMITTED_OPERATOR_CLASSES - classes
        if missing_classes:
            raise DistributedStorageCoverageError(
                "distributed-storage catalogue missing required operator "
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
                meta_payload, path="DistributedStorageMutationOperators.metadata"
            )
            cid_for_structured(meta_payload)
        except Exception as exc:  # noqa: BLE001
            raise DistributedStorageError(
                "metadata must be DAG-JSON structured data without model authority"
            ) from exc
        object.__setattr__(self, "metadata", MappingProxyType(meta_payload))

        computed = cid_for_structured(self._identity_payload_without_catalogue_id())
        if self.catalogue_id is None:
            object.__setattr__(self, "catalogue_id", computed)
        else:
            claimed = _text(self.catalogue_id, "catalogue_id")
            if claimed != computed:
                raise DistributedStorageError(
                    "catalogue_id identity mismatch with recomputed catalogue identity"
                )
            object.__setattr__(self, "catalogue_id", claimed)

    def _identity_payload_without_catalogue_id(self) -> dict[str, Any]:
        return {
            "schema": DISTRIBUTED_STORAGE_OPERATORS_SCHEMA,
            "interface_id": DISTRIBUTED_STORAGE_OPERATORS_INTERFACE,
            "catalogue_version": DISTRIBUTED_STORAGE_OPERATORS_VERSION,
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
            "durability_distinctions": sorted(
                {
                    item.durability_distinction
                    for item in self.operators
                    if item.durability_distinction is not None
                }
            ),
        }

    def identity_payload(self) -> dict[str, Any]:
        payload = self._identity_payload_without_catalogue_id()
        payload["catalogue_id"] = self.catalogue_id
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DISTRIBUTED_STORAGE_OPERATORS_SCHEMA,
            "interface_id": DISTRIBUTED_STORAGE_OPERATORS_INTERFACE,
            "catalogue_version": DISTRIBUTED_STORAGE_OPERATORS_VERSION,
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
            "durability_distinctions": sorted(
                {
                    item.durability_distinction
                    for item in self.operators
                    if item.durability_distinction is not None
                }
            ),
            "catalogue_id": self.catalogue_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DistributedStorageMutationOperators":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != DISTRIBUTED_STORAGE_OPERATORS_SCHEMA:
            raise DistributedStorageError(
                "unsupported DistributedStorageMutationOperators schema version"
            )
        if payload.pop("interface_id") != DISTRIBUTED_STORAGE_OPERATORS_INTERFACE:
            raise DistributedStorageError(
                "unsupported DistributedStorageMutationOperators interface_id"
            )
        version = payload.pop(
            "catalogue_version", DISTRIBUTED_STORAGE_OPERATORS_VERSION
        )
        if version != DISTRIBUTED_STORAGE_OPERATORS_VERSION:
            raise DistributedStorageError(
                "unsupported DistributedStorageMutationOperators catalogue_version"
            )
        payload.pop("operator_cids", None)
        payload.pop("operator_count", None)
        payload.pop("families", None)
        payload.pop("operator_classes", None)
        payload.pop("durability_distinctions", None)
        raw_ops = payload["operators"]
        if not isinstance(raw_ops, list):
            raise DistributedStorageError("operators must be a list")
        operators: list[DistributedStorageOperator] = []
        for entry in raw_ops:
            if not isinstance(entry, Mapping):
                raise DistributedStorageError(
                    "operators entries must be mappings with family and definition"
                )
            definition_raw = entry.get("definition")
            if isinstance(definition_raw, MutationOperatorDefinition):
                definition = definition_raw
            elif isinstance(definition_raw, Mapping):
                definition = MutationOperatorDefinition.from_dict(definition_raw)
            else:
                raise DistributedStorageError(
                    "operators[].definition must be MutationOperatorDefinition or mapping"
                )
            family = entry.get("family")
            if family is None:
                family = definition.metadata.get(_FAMILY_METADATA_KEY)
            spec_id = entry.get("spec_operator_id", definition.operator_id)
            operators.append(
                DistributedStorageOperator(
                    _definition=definition,
                    family=family,
                    spec_operator_id=spec_id,
                )
            )
        return cls(
            operators=operators,
            producer_id=payload.get(
                "producer_id", DISTRIBUTED_STORAGE_OPERATORS_PRODUCER
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
        if isinstance(item, DistributedStorageOperator):
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

    def durability_distinctions(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.durability_distinction
                    for item in self.operators
                    if item.durability_distinction is not None
                }
            )
        )

    def definitions(self) -> tuple[MutationOperatorDefinition, ...]:
        return tuple(item.definition for item in self.operators)

    def list_operators(self) -> tuple[DistributedStorageOperator, ...]:
        return tuple(self.operators)

    def operators_for_family(
        self, family: DistributedStorageFamily | str
    ) -> tuple[DistributedStorageOperator, ...]:
        if isinstance(family, DistributedStorageFamily):
            family_value = family.value
        elif type(family) is str:
            try:
                family_value = DistributedStorageFamily(family).value
            except ValueError as exc:
                raise DistributedStorageError(
                    f"unsupported state/distributed or storage family: {family!r}"
                ) from exc
        else:
            raise DistributedStorageError(
                "family must be DistributedStorageFamily or str"
            )
        return tuple(item for item in self.operators if item.family == family_value)

    def operators_for_class(
        self, operator_class: OperatorClass | str
    ) -> tuple[DistributedStorageOperator, ...]:
        class_value = _normalize_operator_class(operator_class)
        return tuple(
            item
            for item in self.operators
            if item.definition.operator_class == class_value
        )

    def operators_for_durability_distinction(
        self, distinction: str
    ) -> tuple[DistributedStorageOperator, ...]:
        distinction = _text(distinction, "distinction")
        if distinction not in DURABILITY_DISTINCTIONS:
            raise DistributedStorageError(
                f"unsupported durability_distinction: {distinction!r}"
            )
        return tuple(
            item
            for item in self.operators
            if item.durability_distinction == distinction
        )

    def get(
        self,
        operator_id: str,
        operator_version: str | None = None,
    ) -> DistributedStorageOperator:
        operator_id = _text(operator_id, "operator_id")
        matches = [
            item for item in self.operators if item.operator_id == operator_id
        ]
        if not matches:
            raise DistributedStorageError(f"unknown operator_id: {operator_id}")
        if operator_version is None:
            if len(matches) != 1:
                versions = ", ".join(
                    sorted({item.operator_version for item in matches})
                )
                raise DistributedStorageError(
                    f"operator_id {operator_id} is ambiguous across versions "
                    f"({versions}); provide operator_version"
                )
            return matches[0]
        operator_version = _text(operator_version, "operator_version")
        for item in matches:
            if item.operator_version == operator_version:
                return item
        raise DistributedStorageError(
            f"unknown operator: {operator_id}@{operator_version}"
        )

    def get_by_cid(self, operator_cid: str) -> DistributedStorageOperator:
        operator_cid = _text(operator_cid, "operator_cid")
        for item in self.operators:
            if item.operator_cid == operator_cid:
                return item
        raise DistributedStorageError(f"unknown operator_cid: {operator_cid}")

    def operators_for_target(
        self, target: MutationTarget
    ) -> tuple[DistributedStorageOperator, ...]:
        if not isinstance(target, MutationTarget):
            raise DistributedStorageError("target must be a MutationTarget")
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
                producer_id=producer_id or DISTRIBUTED_STORAGE_OPERATORS_PRODUCER,
                notes=notes if notes is not None else self.notes,
                metadata=metadata if metadata is not None else dict(self.metadata),
            )
        except OperatorRegistryError as exc:
            raise DistributedStorageError(str(exc)) from exc

    def register_into(
        self, builder: MutationOperatorRegistryBuilder
    ) -> tuple[MutationOperatorDefinition, ...]:
        """Admit every catalogue operator into a mutable registry builder."""

        if not isinstance(builder, MutationOperatorRegistryBuilder):
            raise DistributedStorageError(
                "builder must be a MutationOperatorRegistryBuilder"
            )
        sealed: list[MutationOperatorDefinition] = []
        for item in self.operators:
            try:
                sealed.append(builder.register(item.definition))
            except OperatorRegistryError as exc:
                raise DistributedStorageError(str(exc)) from exc
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
        """Re-check that every required family, class, and distinction is present."""

        present = set(self.families())
        missing = REQUIRED_DISTRIBUTED_STORAGE_FAMILIES - present
        if missing:
            raise DistributedStorageCoverageError(
                "distributed-storage catalogue missing required families: "
                + ", ".join(sorted(missing))
            )
        missing_classes = ADMITTED_OPERATOR_CLASSES - set(self.operator_classes())
        if missing_classes:
            raise DistributedStorageCoverageError(
                "distributed-storage catalogue missing required operator "
                "classes: " + ", ".join(sorted(missing_classes))
            )
        if not (REQUIRED_STATE_DISTRIBUTED_FAMILIES <= present):
            raise DistributedStorageCoverageError(
                "state/distributed families incomplete: missing "
                + ", ".join(sorted(REQUIRED_STATE_DISTRIBUTED_FAMILIES - present))
            )
        if not (REQUIRED_STORAGE_DURABILITY_FAMILIES <= present):
            raise DistributedStorageCoverageError(
                "storage/durability families incomplete: missing "
                + ", ".join(sorted(REQUIRED_STORAGE_DURABILITY_FAMILIES - present))
            )
        # Commit / sync / checksum / read-back distinctions must all appear.
        distinctions = set(self.durability_distinctions())
        required_distinctions = {
            "durable_commit",
            "directory_sync",
            "checksum",
            "read_back",
        }
        missing_dist = required_distinctions - distinctions
        if missing_dist:
            raise DistributedStorageCoverageError(
                "storage durability distinctions incomplete: missing "
                + ", ".join(sorted(missing_dist))
            )


def build_distributed_storage_operators(
    specs: Iterable[DistributedStorageOperatorSpec] | None = None,
    *,
    producer_id: str = DISTRIBUTED_STORAGE_OPERATORS_PRODUCER,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DistributedStorageMutationOperators:
    """Build a sealed catalogue from specs (defaults: normative full set).

    The sealed ``DistributedStorageMutationOperators@1`` interface always
    requires complete family and class coverage; incomplete assemblies fail
    closed.
    """

    recipe_list = (
        list(distributed_storage_operator_specs()) if specs is None else list(specs)
    )
    if not recipe_list:
        raise DistributedStorageError(
            "distributed-storage catalogue requires at least one operator spec"
        )
    handles: list[DistributedStorageOperator] = []
    for spec in recipe_list:
        if not isinstance(spec, DistributedStorageOperatorSpec):
            raise DistributedStorageError(
                "specs entries must be DistributedStorageOperatorSpec"
            )
        definition = build_distributed_storage_operator(spec)
        handles.append(
            DistributedStorageOperator(
                _definition=definition,
                family=spec.family,
                spec_operator_id=spec.operator_id,
            )
        )
    catalogue = DistributedStorageMutationOperators(
        operators=handles,
        producer_id=producer_id,
        notes=notes
        if notes is not None
        else (
            "Normative state/distributed and storage/durability mutation "
            "operators with transitions, CAS/fencing/leases/ownership/"
            "idempotency/compensation/convergence/proof forests/parents and "
            "durable commit/sync/checksum/read-back distinctions (AAE-019)"
        ),
        metadata=metadata or {"task_id": "AAE-019"},
    )
    catalogue.assert_complete_coverage()
    return catalogue


def default_distributed_storage_operators() -> DistributedStorageMutationOperators:
    """Return the normative sealed catalogue (stable identity across calls)."""

    return build_distributed_storage_operators()


def distributed_storage_operator_definitions() -> (
    tuple[MutationOperatorDefinition, ...]
):
    """Convenience: sealed definitions only, deterministic order."""

    return default_distributed_storage_operators().definitions()


def distributed_storage_operator_specs_list() -> (
    tuple[DistributedStorageOperatorSpec, ...]
):
    """Alias for ``distributed_storage_operator_specs`` (stable export name)."""

    return distributed_storage_operator_specs()


def distributed_storage_families_covered() -> frozenset[str]:
    """Return the family set covered by the normative catalogue."""

    return frozenset(default_distributed_storage_operators().families())


# Alias matching the interface name used in task metadata.
DistributedStorageMutationOperatorsCatalogue = DistributedStorageMutationOperators


__all__ = [
    "ADMITTED_OPERATOR_CLASSES",
    "DEFAULT_STATE_DISTRIBUTED_RISK_CLASS",
    "DEFAULT_STORAGE_DURABILITY_RISK_CLASS",
    "DISTRIBUTED_STORAGE_OPERATORS_INTERFACE",
    "DISTRIBUTED_STORAGE_OPERATORS_PRODUCER",
    "DISTRIBUTED_STORAGE_OPERATORS_SCHEMA",
    "DISTRIBUTED_STORAGE_OPERATORS_VERSION",
    "DISTRIBUTED_STORAGE_OPERATOR_VERSION",
    "DURABILITY_DISTINCTIONS",
    "DistributedStorageCoverageError",
    "DistributedStorageError",
    "DistributedStorageFamily",
    "DistributedStorageMutationOperators",
    "DistributedStorageMutationOperatorsCatalogue",
    "DistributedStorageOperator",
    "DistributedStorageOperatorSpec",
    "REQUIRED_DISTRIBUTED_STORAGE_FAMILIES",
    "REQUIRED_STATE_DISTRIBUTED_FAMILIES",
    "REQUIRED_STORAGE_DURABILITY_FAMILIES",
    "assert_distributed_storage_operator_defaults",
    "build_distributed_storage_operator",
    "build_distributed_storage_operators",
    "default_distributed_storage_operators",
    "distributed_storage_families_covered",
    "distributed_storage_operator_definitions",
    "distributed_storage_operator_specs",
    "distributed_storage_operator_specs_list",
]
