"""Conformance: final generated provider/translation registry closure (LFP-040).

Acceptance:

* Final catalog has no duplicate / eager / unknown entry
* Suite contains every exact provider ID
* Unexplained registry gaps are rejected
* Presence is never availability or proof
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.registry import (
    EXECUTABLE_PROVIDER_ALIASES,
    EXECUTABLE_PROVIDER_IDS,
    EXECUTABLE_PROVIDER_MATRIX,
)
from ipfs_datasets_py.logic.families.generated_catalog import (
    DEFAULT_GENERATED_CATALOG,
    GENERATED_PROVIDER_TRANSLATION_CATALOG_INTERFACE,
    DuplicateGeneratedCatalogEntryError,
    GeneratedCatalogError,
    GeneratedProviderTranslationCatalog,
    GeneratedTranslationEdge,
    UnknownGeneratedCatalogEntryError,
    build_generated_provider_translation_catalog,
)
from ipfs_datasets_py.logic.families.models import (
    EvidenceAuthority,
    TranslationKind,
)
from ipfs_datasets_py.logic.families.providers import (
    ADVISORY_PROVIDER_IDS,
    BASELINE_PROVIDER_CATALOG,
    BASELINE_PROVIDER_IDS,
    ProviderCapabilityEntry,
    ProviderCatalogDriftError,
    ProviderCatalogSource,
)
from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY


def test_generated_catalog_interface_identity() -> None:
    catalog = DEFAULT_GENERATED_CATALOG
    assert (
        catalog.INTERFACE
        == GENERATED_PROVIDER_TRANSLATION_CATALOG_INTERFACE
        == "GeneratedProviderTranslationCatalog@1"
    )
    assert catalog.task_id == "LFP-040"
    assert catalog.generated_closure_open is False
    payload = catalog.to_dict()
    assert payload["interface"] == "GeneratedProviderTranslationCatalog@1"
    restored = GeneratedProviderTranslationCatalog.from_dict(payload)
    assert restored.provider_ids == catalog.provider_ids
    assert restored.translation_ids == catalog.translation_ids


def test_generated_catalog_contains_every_exact_provider_id() -> None:
    catalog = build_generated_provider_translation_catalog(validate=True)
    expected = set(BASELINE_PROVIDER_IDS) | set(EXECUTABLE_PROVIDER_IDS)
    assert set(catalog.provider_ids) == expected

    # Executable matrix exact IDs.
    assert set(catalog.executable_matrix_provider_ids) == set(EXECUTABLE_PROVIDER_IDS)
    assert set(catalog.executable_matrix_provider_ids) == {
        entry.provider_id for entry in EXECUTABLE_PROVIDER_MATRIX
    }

    # Plan-enumerated providers including advisory lanes.
    for provider_id in (
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
        "ergoai",
        "symbolicai",
    ):
        assert provider_id in catalog
        entry = catalog.get_provider(provider_id)
        assert entry.provider_id == provider_id


def test_generated_catalog_preserves_reviewed_aliases() -> None:
    catalog = DEFAULT_GENERATED_CATALOG
    for alias, canonical in EXECUTABLE_PROVIDER_ALIASES.items():
        assert catalog.reviewed_aliases[alias] == canonical
        assert catalog.get_provider(alias).provider_id == canonical
    assert catalog.get_provider("ergo_ai").provider_id == "ergoai"
    assert catalog.get_provider("symai").provider_id == "symbolicai"


def test_generated_catalog_projects_registry_translations() -> None:
    catalog = DEFAULT_GENERATED_CATALOG
    registry_ids = set(DEFAULT_REGISTRY.translations)
    assert registry_ids
    assert registry_ids <= set(catalog.translation_ids)
    for translation_id in registry_ids:
        edge = catalog.get_translation(translation_id)
        source = DEFAULT_REGISTRY.translations[translation_id]
        assert edge.source_family_id == source.source_family_id
        assert edge.target_family_id == source.target_family_id
        assert edge.translation_kind == source.translation_kind


def test_generated_catalog_no_duplicate_eager_or_unknown_entries() -> None:
    catalog = DEFAULT_GENERATED_CATALOG
    assert len(catalog.provider_ids) == len(set(catalog.provider_ids))
    assert len(catalog.translation_ids) == len(set(catalog.translation_ids))
    assert catalog.is_eager() is False
    assert catalog.has_unknown_entries() is False
    catalog.validate_closure()

    for provider_id in catalog.provider_ids:
        assert catalog.claims_availability(provider_id) is False
        assert catalog.claims_proof(provider_id) is False


def test_generated_catalog_rejects_duplicate_providers() -> None:
    base = list(DEFAULT_GENERATED_CATALOG.providers)
    with pytest.raises(DuplicateGeneratedCatalogEntryError, match="duplicate provider"):
        GeneratedProviderTranslationCatalog(
            providers=tuple(base + [base[0]]),
            translations=DEFAULT_GENERATED_CATALOG.translations,
            generated_closure_open=False,
        )


def test_generated_catalog_rejects_duplicate_translations() -> None:
    base = list(DEFAULT_GENERATED_CATALOG.translations)
    with pytest.raises(
        DuplicateGeneratedCatalogEntryError, match="duplicate translation"
    ):
        GeneratedProviderTranslationCatalog(
            providers=DEFAULT_GENERATED_CATALOG.providers,
            translations=tuple(base + [base[0]]),
            generated_closure_open=False,
        )


def test_generated_catalog_rejects_unknown_translation_family() -> None:
    edge = GeneratedTranslationEdge(
        translation_id="bogus_to_nowhere",
        source_family_id="not_a_family",
        target_family_id="first_order",
        translation_kind=TranslationKind.LOSSLESS,
    )
    catalog = GeneratedProviderTranslationCatalog(
        providers=DEFAULT_GENERATED_CATALOG.providers,
        translations=DEFAULT_GENERATED_CATALOG.translations + (edge,),
        generated_closure_open=False,
    )
    with pytest.raises(UnknownGeneratedCatalogEntryError, match="unknown source family"):
        catalog.validate_closure()


def test_generated_catalog_rejects_missing_registry_translation() -> None:
    # Drop one registry translation and ensure closure fails.
    registry_ids = list(DEFAULT_REGISTRY.translations)
    assert registry_ids
    drop = registry_ids[0]
    remaining = tuple(
        edge
        for edge in DEFAULT_GENERATED_CATALOG.translations
        if edge.translation_id != drop
    )
    catalog = GeneratedProviderTranslationCatalog(
        providers=DEFAULT_GENERATED_CATALOG.providers,
        translations=remaining,
        generated_closure_open=False,
    )
    with pytest.raises(
        UnknownGeneratedCatalogEntryError, match="missing registry translations"
    ):
        catalog.validate_closure()


def test_generated_catalog_rejects_open_closure_and_baseline_overwrite() -> None:
    open_catalog = GeneratedProviderTranslationCatalog(
        providers=DEFAULT_GENERATED_CATALOG.providers,
        translations=DEFAULT_GENERATED_CATALOG.translations,
        generated_closure_open=True,
    )
    with pytest.raises(GeneratedCatalogError, match="generated_closure_open"):
        open_catalog.validate_closure()

    # Explicit overwrite of a baseline provider with generated source.
    z3 = DEFAULT_GENERATED_CATALOG.get_provider("z3")
    overwritten = ProviderCapabilityEntry(
        provider_id=z3.provider_id,
        provider_version="generated-v1",
        authority_ceiling=EvidenceAuthority.BOUNDED,
        family_support=z3.family_support,
        aliases=z3.aliases,
        in_executable_matrix=True,
        catalog_source=ProviderCatalogSource.GENERATED_CLOSURE,
    )
    catalog = GeneratedProviderTranslationCatalog(
        providers=tuple(
            overwritten if item.provider_id == "z3" else item
            for item in DEFAULT_GENERATED_CATALOG.providers
        ),
        translations=DEFAULT_GENERATED_CATALOG.translations,
        generated_closure_open=False,
    )
    with pytest.raises(ProviderCatalogDriftError, match="cannot be re-sourced"):
        catalog.validate_closure()


def test_generated_catalog_advisory_providers_retained() -> None:
    catalog = DEFAULT_GENERATED_CATALOG
    for provider_id in ADVISORY_PROVIDER_IDS:
        entry = catalog.get_provider(provider_id)
        assert entry.advisory is True
        assert entry.authority_ceiling is EvidenceAuthority.ADVISORY


def test_baseline_and_generated_projection_are_aligned() -> None:
    baseline = BASELINE_PROVIDER_CATALOG
    generated = DEFAULT_GENERATED_CATALOG
    assert set(baseline.provider_ids) == set(generated.provider_ids)
    for provider_id in baseline.provider_ids:
        assert (
            baseline.get(provider_id).catalog_source
            is ProviderCatalogSource.BASELINE
        )
        assert (
            generated.get_provider(provider_id).catalog_source
            is ProviderCatalogSource.BASELINE
        )
