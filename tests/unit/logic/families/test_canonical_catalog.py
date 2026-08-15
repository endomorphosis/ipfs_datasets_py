"""Contract tests for CanonicalLogicCatalogSnapshot@1 (LPC-020).

Acceptance:

* snapshot composes taxonomy, namespaces, aliases, publication, profiles,
  properties, views, notations, encodings, providers, matrix, lanes, evidence,
  translations, versions, and content identity
* publication ladder distinguishes identity-exists through production-admitted
* declaration never implies executability or production admission
* content root is reproducible
* typed layers are not flattened into one untyped dictionary
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.aliases import (
    ALIAS_INTERFACE,
    BASELINE_ALIAS_REGISTRY,
)
from ipfs_datasets_py.logic.families.canonical_catalog import (
    CANONICAL_CATALOG_GOAL_ID,
    CANONICAL_CATALOG_IDENTITY_DOMAIN,
    CANONICAL_CATALOG_SNAPSHOT_INTERFACE,
    CANONICAL_CATALOG_SNAPSHOT_SCHEMA,
    CANONICAL_CATALOG_SNAPSHOT_VERSION,
    CANONICAL_CATALOG_TASK_ID,
    CatalogPublicationStage,
    DEFAULT_CANONICAL_CATALOG_SNAPSHOT,
    PUBLICATION_LADDER,
    UnknownCatalogIdentityError,
    build_canonical_logic_catalog_snapshot,
)
from ipfs_datasets_py.logic.families.generated_catalog import (
    DEFAULT_GENERATED_CATALOG,
    GENERATED_PROVIDER_TRANSLATION_CATALOG_INTERFACE,
)
from ipfs_datasets_py.logic.families.namespaces import (
    BASELINE_NAMESPACES,
    NAMESPACE_INTERFACE,
    CrossNamespaceCoercionError,
    NamespaceKind,
)
from ipfs_datasets_py.logic.families.profile_catalog_v3 import (
    DEFAULT_PROFILE_CATALOG_V3,
    LOGIC_PROFILE_CATALOG_V3_INTERFACE,
)
from ipfs_datasets_py.logic.families.provider_matrix_v2 import (
    BASELINE_PROVIDER_CAPABILITY_MATRIX_V2,
    MATRIX_V2_INTERFACE,
)
from ipfs_datasets_py.logic.families.providers import (
    BASELINE_PROVIDER_CATALOG,
    CATALOG_INTERFACE as PROVIDER_CATALOG_INTERFACE,
)
from ipfs_datasets_py.logic.families.registry import (
    DEFAULT_REGISTRY,
    REGISTRY_INTERFACE as REGISTRY_V2_INTERFACE,
)
from ipfs_datasets_py.logic.families.registry_v3 import (
    DEFAULT_REGISTRY_V3,
    FamilyLifecycleDisposition,
    LOGIC_FAMILY_REGISTRY_V3_INTERFACE,
)
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity


# ---------------------------------------------------------------------------
# Interface / composition surface
# ---------------------------------------------------------------------------


def test_default_snapshot_interface_and_task_binding() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    assert snapshot.interface == CANONICAL_CATALOG_SNAPSHOT_INTERFACE
    assert snapshot.interface == "CanonicalLogicCatalogSnapshot@1"
    assert snapshot.schema_version == CANONICAL_CATALOG_SNAPSHOT_SCHEMA
    assert snapshot.version == CANONICAL_CATALOG_SNAPSHOT_VERSION
    assert snapshot.task_id == CANONICAL_CATALOG_TASK_ID
    assert snapshot.goal_id == CANONICAL_CATALOG_GOAL_ID
    assert snapshot.task_id == "LPC-020"
    assert snapshot.goal_id == "LPC-G020"


def test_snapshot_composes_every_required_layer() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT

    # Typed layer objects remain distinct (not flattened).
    assert snapshot.taxonomy is DEFAULT_REGISTRY
    assert snapshot.namespaces is BASELINE_NAMESPACES
    assert snapshot.aliases is BASELINE_ALIAS_REGISTRY
    assert snapshot.publication is DEFAULT_REGISTRY_V3
    assert snapshot.profiles is DEFAULT_PROFILE_CATALOG_V3
    assert snapshot.providers is BASELINE_PROVIDER_CATALOG
    assert snapshot.matrix is BASELINE_PROVIDER_CAPABILITY_MATRIX_V2
    assert snapshot.generated is DEFAULT_GENERATED_CATALOG

    assert snapshot.layer_interfaces == {
        "aliases": ALIAS_INTERFACE,
        "generated": GENERATED_PROVIDER_TRANSLATION_CATALOG_INTERFACE,
        "matrix": MATRIX_V2_INTERFACE,
        "namespaces": NAMESPACE_INTERFACE,
        "profiles": LOGIC_PROFILE_CATALOG_V3_INTERFACE,
        "providers": PROVIDER_CATALOG_INTERFACE,
        "publication": LOGIC_FAMILY_REGISTRY_V3_INTERFACE,
        "snapshot": CANONICAL_CATALOG_SNAPSHOT_INTERFACE,
        "taxonomy": REGISTRY_V2_INTERFACE,
    }

    # Acceptance projections.
    assert snapshot.family_ids
    assert "first_order" in snapshot.family_ids
    assert snapshot.properties
    assert "safety" in snapshot.properties
    assert snapshot.views
    assert "source" in snapshot.views
    assert snapshot.notations
    assert "smt_lib2" in snapshot.notations
    assert snapshot.encodings
    assert "lean4" in snapshot.encodings
    assert snapshot.provider_ids
    assert "z3" in snapshot.provider_ids
    assert snapshot.lanes
    assert "smt" in snapshot.lanes
    assert snapshot.evidence
    assert "model" in snapshot.evidence or "checked_proof" in snapshot.evidence
    assert snapshot.translations
    assert snapshot.profile_ids
    assert snapshot.versions
    assert snapshot.versions["taxonomy"] == snapshot.taxonomy.version
    assert snapshot.versions["publication"] == snapshot.publication.version
    assert snapshot.versions["snapshot"] == snapshot.version


def test_builder_matches_default_and_validates() -> None:
    rebuilt = build_canonical_logic_catalog_snapshot(validate=True)
    assert rebuilt.interface == DEFAULT_CANONICAL_CATALOG_SNAPSHOT.interface
    assert rebuilt.content_root == DEFAULT_CANONICAL_CATALOG_SNAPSHOT.content_root
    assert rebuilt.content_digest == DEFAULT_CANONICAL_CATALOG_SNAPSHOT.content_digest


# ---------------------------------------------------------------------------
# Publication ladder
# ---------------------------------------------------------------------------


def test_publication_ladder_is_complete_and_ordered() -> None:
    expected = (
        CatalogPublicationStage.IDENTITY_EXISTS,
        CatalogPublicationStage.DECLARED,
        CatalogPublicationStage.DISCOVERABLE,
        CatalogPublicationStage.PARSE_PRINT,
        CatalogPublicationStage.CONTROLLED_EXECUTABLE,
        CatalogPublicationStage.SHADOW,
        CatalogPublicationStage.CANARY,
        CatalogPublicationStage.PRODUCTION_ADMITTED,
    )
    assert PUBLICATION_LADDER == expected
    assert [stage.value for stage in PUBLICATION_LADDER] == [
        "identity_exists",
        "declared",
        "discoverable",
        "parse_print",
        "controlled_executable",
        "shadow",
        "canary",
        "production_admitted",
    ]


def test_publication_stage_maps_registry_v3_dispositions() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT

    # Taxonomy-declared families that are not Wave-2 publications stay declared.
    if "first_order" not in snapshot.publication:
        assert (
            snapshot.publication_stage("first_order")
            is CatalogPublicationStage.DECLARED
        )

    for entry in snapshot.publication.entries:
        stage = snapshot.publication_stage(entry.family_id)
        if entry.disposition is FamilyLifecycleDisposition.CONTROLLED_EXECUTABLE:
            assert stage is CatalogPublicationStage.CONTROLLED_EXECUTABLE
            assert snapshot.claims_executability(entry.family_id)
        elif entry.disposition is FamilyLifecycleDisposition.PARSE_PRINT:
            assert stage is CatalogPublicationStage.PARSE_PRINT
        else:
            assert stage is CatalogPublicationStage.DECLARED
            assert not snapshot.claims_executability(entry.family_id)

        # Production admission is never inferred from presence.
        assert snapshot.is_production_admitted(entry.family_id) is False
        assert stage is not CatalogPublicationStage.PRODUCTION_ADMITTED


def test_declaration_never_implies_executability_or_production() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    assert snapshot.presence_implies_executability() is False
    assert snapshot.presence_implies_production_admission() is False
    assert snapshot.publication.presence_implies_executability() is False
    assert snapshot.profiles.presence_implies_executability() is False

    for family_id in snapshot.publication.declaration_only_family_ids:
        assert snapshot.claims_executability(family_id) is False
        assert snapshot.is_production_admitted(family_id) is False
        assert (
            snapshot.publication_stage(family_id)
            is CatalogPublicationStage.DECLARED
        )


def test_unknown_family_fails_closed_on_publication_stage() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    with pytest.raises(UnknownCatalogIdentityError):
        snapshot.publication_stage("not_a_real_family_zzzz")


def test_stage_at_least_respects_ladder_order() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    # Pick any known published family.
    family_id = snapshot.publication.family_ids[0]
    stage = snapshot.publication_stage(family_id)
    assert snapshot.stage_at_least(family_id, CatalogPublicationStage.IDENTITY_EXISTS)
    assert snapshot.stage_at_least(family_id, stage)
    if stage is not CatalogPublicationStage.PRODUCTION_ADMITTED:
        assert not snapshot.stage_at_least(
            family_id, CatalogPublicationStage.PRODUCTION_ADMITTED
        )


# ---------------------------------------------------------------------------
# Content identity / reproducibility
# ---------------------------------------------------------------------------


def test_content_root_is_reproducible() -> None:
    first = build_canonical_logic_catalog_snapshot(validate=True)
    second = build_canonical_logic_catalog_snapshot(validate=True)
    assert first.content_root == second.content_root
    assert first.content_digest == second.content_digest
    assert first.content_digest.startswith("sha256:")
    assert first.content_root.startswith("b")

    identity = first.content_identity()
    recomputed = canonical_identity(
        first.layer_envelope(),
        domain=CANONICAL_CATALOG_IDENTITY_DOMAIN,
        schema_version=first.schema_version,
    )
    assert identity.cid == recomputed.cid
    assert identity.digest == recomputed.digest
    assert identity.domain == CANONICAL_CATALOG_IDENTITY_DOMAIN


def test_to_dict_and_to_json_are_deterministic() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    payload = snapshot.to_dict()
    assert payload["interface"] == CANONICAL_CATALOG_SNAPSHOT_INTERFACE
    assert payload["schema_version"] == CANONICAL_CATALOG_SNAPSHOT_SCHEMA
    assert payload["presence_implies_executability"] is False
    assert payload["presence_implies_production_admission"] is False
    assert "taxonomy" in payload and isinstance(payload["taxonomy"], dict)
    assert "namespaces" in payload and isinstance(payload["namespaces"], dict)
    assert "aliases" in payload and isinstance(payload["aliases"], dict)
    assert "publication" in payload and isinstance(payload["publication"], dict)
    assert "profiles" in payload and isinstance(payload["profiles"], dict)
    assert "providers" in payload and isinstance(payload["providers"], dict)
    assert "matrix" in payload and isinstance(payload["matrix"], dict)
    assert "generated" in payload and isinstance(payload["generated"], dict)
    assert payload["properties"]
    assert payload["views"]
    assert payload["notations"]
    assert payload["encodings"]
    assert payload["lanes"]
    assert payload["evidence"]
    assert payload["translations"]
    assert payload["versions"]

    text_a = snapshot.to_json()
    text_b = snapshot.to_json()
    assert text_a == text_b
    decoded = json.loads(text_a)
    assert decoded["interface"] == CANONICAL_CATALOG_SNAPSHOT_INTERFACE


def test_layers_remain_typed_not_flattened_dict() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    # Composition keeps concrete layer types.
    assert type(snapshot.taxonomy).__name__ == "LogicFamilyRegistry"
    assert type(snapshot.namespaces).__name__ == "LogicIdentityNamespaces"
    assert type(snapshot.aliases).__name__ == "LogicAliasRegistry"
    assert type(snapshot.publication).__name__ == "LogicFamilyRegistryV3"
    assert type(snapshot.profiles).__name__ == "LogicProfileCatalogV3"
    assert type(snapshot.providers).__name__ == "ProviderCapabilityCatalog"
    assert type(snapshot.matrix).__name__ == "ProviderCapabilityMatrixV2"
    assert type(snapshot.generated).__name__ == "GeneratedProviderTranslationCatalog"

    # Namespace roles stay non-interchangeable under the snapshot.
    family = snapshot.namespaces.resolve(NamespaceKind.FAMILY, "first_order")
    with pytest.raises(CrossNamespaceCoercionError):
        family.require(NamespaceKind.PROVIDER)


def test_snapshot_dataclass_is_frozen() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    with pytest.raises(FrozenInstanceError):
        snapshot.version = "2.0.0"  # type: ignore[misc]


def test_validate_passes_for_default_composition() -> None:
    snapshot = build_canonical_logic_catalog_snapshot(validate=False)
    snapshot.validate()
    assert snapshot.presence_implies_executability() is False
    assert snapshot.presence_implies_production_admission() is False


def test_namespace_role_projections_cover_acceptance_surface() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    # Every NamespaceKind used by LPC-020 acceptance is populated.
    for kind in (
        NamespaceKind.FAMILY,
        NamespaceKind.PROFILE,
        NamespaceKind.PROPERTY,
        NamespaceKind.VIEW,
        NamespaceKind.NOTATION,
        NamespaceKind.ENCODING,
        NamespaceKind.PROVIDER,
        NamespaceKind.LANE,
        NamespaceKind.EVIDENCE,
    ):
        assert snapshot.namespaces.bindings(kind)
