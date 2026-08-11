"""Acceptance tests for ProviderCapabilityCatalog@1 and baseline registry join."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.backends.registry import (
    EXECUTABLE_PROVIDER_ALIASES,
    EXECUTABLE_PROVIDER_IDS,
    EXECUTABLE_PROVIDER_MATRIX,
    EXECUTABLE_PROVIDER_MATRIX_INTERFACE,
    declared_backend_catalog,
    default_backend_registry,
    provider_matrix_declarations,
)
from ipfs_datasets_py.logic.families.models import (
    EvidenceAuthority,
    FamilySupportDescriptor,
    SupportLevel,
)
from ipfs_datasets_py.logic.families.providers import (
    ADVISORY_AUTHORITY_CEILINGS,
    ADVISORY_PROVIDER_IDS,
    BASELINE_PROVIDER_CATALOG,
    BASELINE_PROVIDER_IDS,
    CATALOG_INTERFACE,
    CATALOG_SCHEMA_VERSION,
    EXECUTABLE_MATRIX_PROVIDER_IDS,
    GENERATED_CLOSURE_TASK,
    ProviderAvailabilityPosture,
    ProviderCapabilityCatalog,
    ProviderCapabilityEntry,
    ProviderCatalogAuthorityError,
    ProviderCatalogDriftError,
    ProviderCatalogError,
    ProviderCatalogSource,
    REVIEWED_EXECUTABLE_PROVIDER_ALIASES,
    authority_at_most,
    build_baseline_provider_catalog,
    build_baseline_provider_entries,
    register_baseline_provider_capabilities,
)
from ipfs_datasets_py.logic.families.registry import (
    BASELINE_FAMILY_IDS,
    DECLARATION_ONLY_FAMILY_IDS,
    DEFAULT_REGISTRY,
    FOUNDATION_FAMILY_IDS,
    NON_FAMILY_PROFILE_LABELS,
    PLANNED_EXTENSION_FAMILY_IDS,
    REGISTRY_INTERFACE,
    build_default_registry,
)


REQUIRED_EXECUTABLE_IDS = {
    "z3",
    "cvc5",
    "tla_tlc",
    "apalache",
    "datalog_secpal",
    "proverif",
    "tamarin",
    "hyperltl_autohyper_mchyper",
    "vampire",
    "eprover",
    "hammer",
    "lean",
    "rocq",
    "isabelle",
    "runtime_mtl",
}

REQUIRED_BASELINE_PROVIDERS = REQUIRED_EXECUTABLE_IDS | {"ergoai", "symbolicai"}

PLANNED_EXTENSIONS = {
    "epistemic",
    "doxastic",
    "intention_agency",
    "session_process",
}

DECLARATION_ONLY = {
    "dependent_type",
    "description_logic",
    "defeasible_logic",
    "nonmonotonic_logic",
    "argumentation",
    "situation_calculus",
    "probabilistic",
    "fuzzy_weighted",
    "relevance_paraconsistent",
    "finite_field_constraint",
}


def test_catalog_interface_and_schema_versions() -> None:
    catalog = BASELINE_PROVIDER_CATALOG
    assert catalog.interface == CATALOG_INTERFACE
    assert catalog.schema_version == CATALOG_SCHEMA_VERSION
    assert catalog.interface == "ProviderCapabilityCatalog@1"
    assert REGISTRY_INTERFACE == "LogicFamilyRegistry@2"
    assert catalog.generated_closure_task == GENERATED_CLOSURE_TASK
    assert catalog.generated_closure_open is True


def test_baseline_registry_enumerates_planned_and_declaration_only_families() -> None:
    families = set(DEFAULT_REGISTRY.families)
    assert PLANNED_EXTENSIONS <= families
    assert DECLARATION_ONLY <= families
    assert PLANNED_EXTENSIONS == set(PLANNED_EXTENSION_FAMILY_IDS)
    assert DECLARATION_ONLY <= set(DECLARATION_ONLY_FAMILY_IDS)
    assert set(BASELINE_FAMILY_IDS) == families
    assert FOUNDATION_FAMILY_IDS <= families

    for family_id in DECLARATION_ONLY | {"mu_calculus"}:
        descriptor = DEFAULT_REGISTRY.families[family_id]
        assert descriptor.declaration_only
        assert not descriptor.operation_ids

    for family_id in PLANNED_EXTENSIONS:
        descriptor = DEFAULT_REGISTRY.families[family_id]
        assert not descriptor.declaration_only
        assert descriptor.operation_ids


def test_no_free_form_family_drift_or_profile_promotion() -> None:
    # dynamic_logic remains a program alias, not a family.
    assert "dynamic_logic" not in DEFAULT_REGISTRY.families
    assert DEFAULT_REGISTRY.resolve("dynamic_logic").family_id == "program"
    assert "dynamic_logic" in NON_FAMILY_PROFILE_LABELS

    # information_flow remains a hyperproperty profile/fragment, not a family.
    assert "information_flow" not in DEFAULT_REGISTRY.families
    assert "information_flow" in NON_FAMILY_PROFILE_LABELS
    hyper = DEFAULT_REGISTRY.families["hyperproperty"]
    assert "information_flow" in hyper.fragment_ids

    # Catalog rejects free-form family claims.
    with pytest.raises(ProviderCatalogDriftError, match="outside the baseline"):
        ProviderCapabilityEntry(
            provider_id="z3",
            provider_version="test-v1",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            family_support=(
                FamilySupportDescriptor("not_a_real_family", SupportLevel.NATIVE),
            ),
            in_executable_matrix=True,
        )

    with pytest.raises(ProviderCatalogDriftError, match="non-family profile"):
        ProviderCapabilityEntry(
            provider_id="z3",
            provider_version="test-v1",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            family_support=(
                FamilySupportDescriptor("dynamic_logic", SupportLevel.NATIVE),
            ),
            in_executable_matrix=True,
        )


def test_catalog_enumerates_every_executable_matrix_id_and_reviewed_alias() -> None:
    catalog = BASELINE_PROVIDER_CATALOG
    assert set(EXECUTABLE_MATRIX_PROVIDER_IDS) == REQUIRED_EXECUTABLE_IDS
    assert set(EXECUTABLE_PROVIDER_IDS) == REQUIRED_EXECUTABLE_IDS
    assert set(catalog.executable_matrix_ids) == REQUIRED_EXECUTABLE_IDS
    assert set(BASELINE_PROVIDER_IDS) == REQUIRED_BASELINE_PROVIDERS
    assert set(catalog.provider_ids) == REQUIRED_BASELINE_PROVIDERS

    # Exact join with backend matrix declarations.
    catalog.validate_executable_matrix_join()
    matrix_ids = {entry.provider_id for entry in EXECUTABLE_PROVIDER_MATRIX}
    assert matrix_ids == REQUIRED_EXECUTABLE_IDS
    assert provider_matrix_declarations() is EXECUTABLE_PROVIDER_MATRIX

    # Every reviewed matrix alias is dual-readable in the catalog.
    assert dict(REVIEWED_EXECUTABLE_PROVIDER_ALIASES) == dict(
        EXECUTABLE_PROVIDER_ALIASES
    )
    expected_aliases = {
        "tlc": "tla_tlc",
        "datalog-authorization": "datalog_secpal",
        "secpal-authorization": "datalog_secpal",
        "hyperltl": "hyperltl_autohyper_mchyper",
        "autohyper": "hyperltl_autohyper_mchyper",
        "mchyper": "hyperltl_autohyper_mchyper",
        "e": "eprover",
        "coq": "rocq",
        "coqc": "rocq",
    }
    for alias, canonical in expected_aliases.items():
        assert REVIEWED_EXECUTABLE_PROVIDER_ALIASES[alias] == canonical
        assert catalog.resolve(alias).provider_id == canonical
        assert catalog.reviewed_aliases[alias] == canonical

    # Advisory reviewed aliases.
    assert catalog.resolve("ergo_ai").provider_id == "ergoai"
    assert catalog.resolve("symai").provider_id == "symbolicai"


def test_baseline_distinct_from_lfp040_generated_closure() -> None:
    catalog = BASELINE_PROVIDER_CATALOG
    assert catalog.generated_closure_task == "LFP-040"
    assert catalog.generated_closure_open is True
    assert all(entry.is_baseline for entry in catalog)
    assert catalog.generated_closure_entries == ()
    assert all(
        entry.catalog_source is ProviderCatalogSource.BASELINE
        for entry in catalog.baseline_entries
    )

    # Generated-closure rows cannot overwrite sealed baseline providers.
    mutable = ProviderCapabilityCatalog(frozen=False)
    for entry in build_baseline_provider_entries():
        mutable.register(entry)
    with pytest.raises(ProviderCatalogDriftError, match="cannot overwrite baseline"):
        mutable.register(
            ProviderCapabilityEntry(
                provider_id="z3",
                provider_version="generated-v1",
                authority_ceiling=EvidenceAuthority.BOUNDED,
                family_support=(),
                in_executable_matrix=True,
                catalog_source=ProviderCatalogSource.GENERATED_CLOSURE,
            )
        )

    # Non-baseline extension slots remain available for LFP-040.
    extension = ProviderCapabilityEntry(
        provider_id="future_domain_provider",
        provider_version="generated-v1",
        authority_ceiling=EvidenceAuthority.NONE,
        family_support=(),
        in_executable_matrix=False,
        availability_posture=ProviderAvailabilityPosture.NOT_DECLARED,
        catalog_source=ProviderCatalogSource.GENERATED_CLOSURE,
        notes="Placeholder for LFP-040 generated closure only.",
    )
    mutable.register(extension)
    assert extension.is_generated_closure
    assert not extension.is_baseline
    assert len(mutable.generated_closure_entries) == 1


def test_presence_is_never_availability_or_proof() -> None:
    catalog = BASELINE_PROVIDER_CATALOG
    for provider_id in catalog.provider_ids:
        assert catalog.is_available(provider_id) is False
        assert catalog.claims_proof(provider_id) is False
        entry = catalog.get(provider_id)
        assert entry.availability_posture in {
            ProviderAvailabilityPosture.DECLARED,
            ProviderAvailabilityPosture.ADVISORY_ONLY,
        }
        # Declared posture is not a live install claim.
        assert entry.availability_posture is not ProviderAvailabilityPosture.UNKNOWN

    # Backend discovery catalog stays declaration-only as well.
    declared = declared_backend_catalog()
    assert {item["provider_id"] for item in declared} == set(
        EXECUTABLE_MATRIX_PROVIDER_IDS
    )
    assert all(item["availability"] == "declared" for item in declared)
    assert all(
        item["metadata"]["executable_provider_matrix"]
        == EXECUTABLE_PROVIDER_MATRIX_INTERFACE
        for item in declared
    )

    # Lazy matrix construction still does not probe tools.
    registry = default_backend_registry()
    assert set(registry) == set(EXECUTABLE_MATRIX_PROVIDER_IDS)


def test_advisory_providers_have_hard_authority_ceilings() -> None:
    catalog = BASELINE_PROVIDER_CATALOG
    assert ADVISORY_PROVIDER_IDS == frozenset({"ergoai", "hammer", "symbolicai"})
    for provider_id, ceiling in ADVISORY_AUTHORITY_CEILINGS.items():
        entry = catalog.get(provider_id)
        assert entry.advisory is True
        assert entry.authority_ceiling is ceiling
        assert entry.authority_ceiling is EvidenceAuthority.ADVISORY
        assert authority_at_most(entry.authority_ceiling, EvidenceAuthority.ADVISORY)
        assert "candidate" in entry.evidence_ids or entry.evidence_ids == ("candidate",)
        assert not (
            set(entry.evidence_ids)
            & {
                "kernel_checked_proof",
                "checked_proof",
                "proof_certificate",
                "attestation",
            }
        )

    # Hard ceiling enforcement rejects inflation.
    with pytest.raises(ProviderCatalogAuthorityError, match="hard ceiling"):
        ProviderCapabilityEntry(
            provider_id="symbolicai",
            provider_version="test-v1",
            authority_ceiling=EvidenceAuthority.AUTHORITATIVE,
            family_support=(),
            advisory=True,
            in_executable_matrix=False,
            availability_posture=ProviderAvailabilityPosture.ADVISORY_ONLY,
        )

    with pytest.raises(ProviderCatalogAuthorityError, match="must be marked advisory"):
        ProviderCapabilityEntry(
            provider_id="ergoai",
            provider_version="test-v1",
            authority_ceiling=EvidenceAuthority.ADVISORY,
            family_support=(),
            advisory=False,
            in_executable_matrix=False,
        )

    with pytest.raises(ProviderCatalogAuthorityError, match="authoritative evidence"):
        ProviderCapabilityEntry(
            provider_id="hammer",
            provider_version="test-v1",
            authority_ceiling=EvidenceAuthority.ADVISORY,
            family_support=(),
            evidence_ids=("kernel_checked_proof",),
            advisory=True,
            in_executable_matrix=True,
        )


def test_entries_validate_against_family_registry() -> None:
    catalog = build_baseline_provider_catalog(frozen=True, validate=True)
    catalog.validate_against_registry(DEFAULT_REGISTRY)

    registry = register_baseline_provider_capabilities(
        build_default_registry(frozen=False)
    )
    assert set(registry.provider_capabilities) == {
        f"{provider_id}@baseline-v1" for provider_id in REQUIRED_BASELINE_PROVIDERS
    }
    for capability in registry.provider_capabilities.values():
        assert capability.provider_id in REQUIRED_BASELINE_PROVIDERS


def test_entry_round_trip_and_immutability() -> None:
    entry = BASELINE_PROVIDER_CATALOG.get("z3")
    restored = ProviderCapabilityEntry.from_dict(entry.to_dict())
    assert restored.to_dict() == entry.to_dict()
    assert restored.capability_id == "z3@baseline-v1"
    with pytest.raises(FrozenInstanceError):
        entry.provider_id = "mutated"  # type: ignore[misc]

    catalog = BASELINE_PROVIDER_CATALOG
    payload = catalog.to_dict()
    assert payload["interface"] == CATALOG_INTERFACE
    assert payload["schema_version"] == CATALOG_SCHEMA_VERSION
    assert set(payload["executable_matrix_provider_ids"]) == REQUIRED_EXECUTABLE_IDS
    assert set(payload["planned_extension_family_ids"]) == PLANNED_EXTENSIONS
    assert "dependent_type" in payload["declaration_only_family_ids"]
    assert "dynamic_logic" in payload["non_family_profile_labels"]
    assert "information_flow" in payload["non_family_profile_labels"]
    assert payload["generated_closure_task"] == "LFP-040"

    reloaded = ProviderCapabilityCatalog.from_dict(payload, frozen=True)
    assert reloaded.to_dict() == payload
    assert reloaded.to_json() == catalog.to_json()
    json.loads(reloaded.to_json())

    with pytest.raises(ProviderCatalogError, match="frozen"):
        reloaded.register(entry)


def test_backend_registry_exports_exact_matrix_ids_and_aliases() -> None:
    assert tuple(EXECUTABLE_PROVIDER_IDS) == EXECUTABLE_MATRIX_PROVIDER_IDS
    assert set(EXECUTABLE_PROVIDER_IDS) == REQUIRED_EXECUTABLE_IDS
    for entry in EXECUTABLE_PROVIDER_MATRIX:
        for alias in entry.aliases:
            assert EXECUTABLE_PROVIDER_ALIASES[alias] == entry.provider_id
            assert REVIEWED_EXECUTABLE_PROVIDER_ALIASES[alias] == entry.provider_id
