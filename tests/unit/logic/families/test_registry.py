"""Contract tests for the canonical logic-family taxonomy."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.models import (
    BoundednessDescriptor,
    BoundednessKind,
    FamilySupportDescriptor,
    LogicFamilyDescriptor,
    LogicFragmentDescriptor,
    LogicOperationDescriptor,
    LogicPropertyDescriptor,
    ProviderCapabilityDescriptor,
    SupportLevel,
    TAXONOMY_SCHEMA_VERSION,
    TaxonomyError,
    TranslationDescriptor,
    TranslationKind,
)
from ipfs_datasets_py.logic.families.registry import (
    DEFAULT_REGISTRY,
    AliasCollisionError,
    FrozenRegistryError,
    InvalidCapabilityError,
    LogicFamilyRegistry,
    SemanticEquivalenceError,
    UnknownDescriptorError,
    build_default_registry,
)


def _family(
    family_id: str,
    *,
    semantic_identity: str | None = None,
    aliases: tuple[str, ...] = (),
    equivalent_to: str | None = None,
) -> LogicFamilyDescriptor:
    return LogicFamilyDescriptor(
        family_id=family_id,
        name=family_id.replace("_", " ").title(),
        semantic_identity=semantic_identity or f"test-semantics/{family_id}/v1",
        aliases=aliases,
        equivalent_to=equivalent_to,
    )


def test_default_registry_covers_existing_and_planned_taxonomy() -> None:
    expected_families = {
        "authorization",
        "concurrency",
        "cryptographic_protocol",
        "datalog",
        "dcec",
        "deontic",
        "event_calculus",
        "first_order",
        "frame_logic",
        "higher_order",
        "horn_chc",
        "hyperproperty",
        "modal",
        "mu_calculus",
        "program",
        "propositional",
        "refinement",
        "separation_logic",
        "tdfol",
        "temporal",
        "transition_system",
    }

    assert expected_families <= set(DEFAULT_REGISTRY.families)
    assert {"pdr", "ic3", "fixedpoint"} <= set(DEFAULT_REGISTRY.operations)
    assert {"horn_clauses", "linear_time", "heap", "symbolic_crypto"} <= set(
        DEFAULT_REGISTRY.fragments
    )
    assert DEFAULT_REGISTRY.families["mu_calculus"].declaration_only
    assert not DEFAULT_REGISTRY.families["mu_calculus"].operation_ids

    horn = DEFAULT_REGISTRY.resolve("Horn/CHC")
    assert horn.family_id == "horn_chc"
    assert {"pdr", "ic3", "fixedpoint"} <= set(horn.operation_ids)
    assert DEFAULT_REGISTRY.resolve("fol") is DEFAULT_REGISTRY.resolve("first-order")
    assert DEFAULT_REGISTRY.resolve("CTL*").family_id == "temporal"
    assert DEFAULT_REGISTRY.resolve("TDFOL").family_id == "tdfol"


def test_descriptors_are_versioned_immutable_and_canonicalize_sets() -> None:
    descriptor = LogicOperationDescriptor(
        "prove_example",
        "Prove example",
        "test-operation/prove-example/v1",
        property_ids=("theorem", "safety"),
        aliases=("zeta", "alpha"),
    )

    assert descriptor.schema_version == TAXONOMY_SCHEMA_VERSION
    assert descriptor.version == "1.0.0"
    assert descriptor.property_ids == ("safety", "theorem")
    assert descriptor.aliases == ("alpha", "zeta")
    with pytest.raises(FrozenInstanceError):
        descriptor.name = "Changed"  # type: ignore[misc]


def test_aliases_are_normalized_but_collisions_are_rejected() -> None:
    registry = LogicFamilyRegistry()
    registry.register_family(_family("alpha", aliases=("Alpha Logic",)))

    assert registry.resolve(" alpha-logic ").family_id == "alpha"
    with pytest.raises(AliasCollisionError, match="collides"):
        registry.register_family(_family("beta", aliases=("alpha_logic",)))
    with pytest.raises(AliasCollisionError, match="colliding aliases"):
        registry.register_family(
            _family("gamma", aliases=("Gamma Logic", "gamma-logic"))
        )


def test_semantic_equivalence_must_be_explicit() -> None:
    registry = LogicFamilyRegistry()
    registry.register_family(
        _family("canonical", semantic_identity="shared-semantics/v1")
    )

    with pytest.raises(SemanticEquivalenceError, match="silently duplicates"):
        registry.register_family(
            _family("silent_copy", semantic_identity="shared-semantics/v1")
        )

    explicit = registry.register_family(
        _family(
            "declared_copy",
            semantic_identity="shared-semantics/v1",
            equivalent_to="canonical",
        )
    )
    assert explicit.equivalent_to == "canonical"


@pytest.mark.parametrize(
    "support_level",
    [
        SupportLevel.NATIVE,
        SupportLevel.TRANSLATED,
        SupportLevel.DECLARATION_ONLY,
        SupportLevel.UNSUPPORTED,
    ],
)
def test_support_level_has_stable_wire_values(support_level: SupportLevel) -> None:
    assert SupportLevel(support_level.value) is support_level


def test_provider_capability_declares_all_support_modes_without_execution() -> None:
    descriptor = ProviderCapabilityDescriptor(
        provider_id="example_solver",
        provider_version="2.1.0",
        family_support=(
            FamilySupportDescriptor(
                "first_order",
                SupportLevel.NATIVE,
                operation_ids=("check_satisfiability", "prove"),
            ),
            FamilySupportDescriptor(
                "propositional",
                SupportLevel.TRANSLATED,
                operation_ids=("check_satisfiability", "prove"),
                translation_ids=("propositional_to_first_order",),
            ),
            FamilySupportDescriptor(
                "mu_calculus", SupportLevel.DECLARATION_ONLY
            ),
            FamilySupportDescriptor("dcec", SupportLevel.UNSUPPORTED),
        ),
        runtime_ids=("native_process",),
        evidence_ids=("checked_proof", "model"),
        boundedness_ids=("resource_bounded",),
        translation_ids=("propositional_to_first_order",),
        deterministic=True,
        metadata={"protocol": "example-provider/v1"},
    )

    registry = build_default_registry(frozen=False)
    assert registry.validate_provider_capability(descriptor) is descriptor
    registry.register_provider_capability(descriptor)

    assert descriptor.support_for("first_order").level is SupportLevel.NATIVE
    assert descriptor.supports("first_order", operation_id="prove")
    assert descriptor.support_for("dcec").level is SupportLevel.UNSUPPORTED
    assert descriptor.support_for("temporal").level is SupportLevel.UNSUPPORTED
    assert not descriptor.supports("mu_calculus")
    assert descriptor.supports("mu_calculus", include_declarations=True)
    assert (
        registry.capability("example_solver", "2.1.0").capability_id
        == "example_solver@2.1.0"
    )


def test_capability_validation_rejects_overclaiming_and_dangling_references() -> None:
    registry = build_default_registry(frozen=False)
    overclaim = ProviderCapabilityDescriptor(
        "bad_solver",
        "1.0.0",
        (
            FamilySupportDescriptor(
                "first_order",
                SupportLevel.NATIVE,
                operation_ids=("pdr",),
            ),
        ),
    )
    unknown_runtime = ProviderCapabilityDescriptor(
        "bad_runtime",
        "1.0.0",
        (FamilySupportDescriptor("first_order", SupportLevel.NATIVE),),
        runtime_ids=("not_installed_by_discovery",),
    )

    with pytest.raises(InvalidCapabilityError, match="outside family"):
        registry.validate_provider_capability(overclaim)
    with pytest.raises(UnknownDescriptorError, match="unknown runtimes"):
        registry.validate_provider_capability(unknown_runtime)


def test_support_and_translation_models_reject_semantic_contradictions() -> None:
    with pytest.raises(TaxonomyError, match="translated support"):
        FamilySupportDescriptor("first_order", SupportLevel.TRANSLATED)
    with pytest.raises(TaxonomyError, match="unsupported"):
        FamilySupportDescriptor(
            "first_order", SupportLevel.UNSUPPORTED, operation_ids=("prove",)
        )
    with pytest.raises(TaxonomyError, match="lossless"):
        TranslationDescriptor(
            "bad_translation",
            "first_order",
            "propositional",
            TranslationKind.LOSSLESS,
            loses_property_ids=("validity",),
        )
    with pytest.raises(TaxonomyError, match="at least one limit"):
        BoundednessDescriptor(
            "bad_bound", "Bad bound", BoundednessKind.STEP_BOUNDED
        )


def test_registration_rejects_dangling_family_vocabulary() -> None:
    registry = LogicFamilyRegistry()
    with pytest.raises(UnknownDescriptorError, match="unknown fragments"):
        registry.register_family(
            LogicFamilyDescriptor(
                "dangling",
                "Dangling",
                "test-semantics/dangling/v1",
                fragment_ids=("missing",),
            )
        )

    registry.register_property(
        LogicPropertyDescriptor("known", "Known", "test-property/known/v1")
    )
    with pytest.raises(UnknownDescriptorError, match="unknown properties"):
        registry.register_operation(
            LogicOperationDescriptor(
                "invalid_operation",
                "Invalid operation",
                "test-operation/invalid/v1",
                property_ids=("missing",),
            )
        )


def test_registry_serialization_is_deterministic_and_round_trips() -> None:
    first = LogicFamilyRegistry(
        fragments=(
            LogicFragmentDescriptor("zeta", "Zeta", "fragment/zeta/v1"),
            LogicFragmentDescriptor("alpha", "Alpha", "fragment/alpha/v1"),
        ),
        families=(
            LogicFamilyDescriptor(
                "zeta", "Zeta", "family/zeta/v1", fragment_ids=("zeta",)
            ),
            LogicFamilyDescriptor(
                "alpha", "Alpha", "family/alpha/v1", fragment_ids=("alpha",)
            ),
        ),
    )
    second = LogicFamilyRegistry(
        fragments=reversed(tuple(first.fragments.values())),
        families=reversed(tuple(first.families.values())),
    )

    assert first.to_json() == second.to_json()
    assert list(first.to_dict()["families"])[0]["family_id"] == "alpha"
    decoded = json.loads(first.to_json())
    assert decoded["schema_version"] == TAXONOMY_SCHEMA_VERSION
    restored = LogicFamilyRegistry.from_json(first.to_json(), frozen=True)
    assert restored.to_json() == first.to_json()
    assert restored.frozen


def test_default_registry_is_frozen_and_exposes_read_only_mappings() -> None:
    with pytest.raises(FrozenRegistryError):
        DEFAULT_REGISTRY.register_family(_family("late_registration"))
    with pytest.raises(TypeError):
        DEFAULT_REGISTRY.families["late_registration"] = _family(  # type: ignore[index]
            "late_registration"
        )


def test_registry_import_does_not_load_provider_or_solver_runtimes() -> None:
    script = """
import json
import sys
from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY
forbidden = (
    "ipfs_datasets_py.logic.backends",
    "ipfs_datasets_py.logic.external_provers",
    "z3",
    "cvc5",
)
print(json.dumps(sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
)))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == []
