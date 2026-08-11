"""Conformance: Wave-2 family route publication (LFP2-044).

Acceptance:

* Every family task (LFP2-037..043) has an exact registry/profile entry
* Every admitted new family-to-domain/provider route is reviewed,
  feature-compatible, and loss/authority receipted
* Registry presence alone never implies executability
* Every executable profile has representative fixtures and deterministic
  resource limits

Interfaces: LogicFamilyRegistry@3, LogicProfileCatalog@3,
FamilyRoutePublication@1, DomainFamilyBindings@2, LogicConformanceCorpus@2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest

from ipfs_datasets_py.logic.conformance.domain_family_bindings_v2 import (
    DEFAULT_DOMAIN_FAMILY_BINDINGS,
    DOMAIN_FAMILY_BINDINGS_V2_INTERFACE,
    DomainBindingStatus,
    DomainFamilyBindingsV2,
    SUPPORTED_DOMAIN_IDS,
    build_default_domain_family_bindings,
)
from ipfs_datasets_py.logic.families.profile_catalog_v3 import (
    DEFAULT_PROFILE_CATALOG_V3,
    LOGIC_PROFILE_CATALOG_V3_INTERFACE,
    REQUIRED_FIXTURE_KINDS,
    LogicProfileCatalogV3,
    ProfileDisposition,
    build_default_profile_catalog_v3,
)
from ipfs_datasets_py.logic.families.registry_v3 import (
    DEFAULT_REGISTRY_V3,
    LOGIC_FAMILY_REGISTRY_V3_INTERFACE,
    WAVE2_FAMILY_TASK_IDS,
    FamilyLifecycleDisposition,
    LogicFamilyRegistryV3,
    build_default_registry_v3,
)
from ipfs_datasets_py.logic.translations.family_extensions import (
    DEFAULT_FAMILY_EXTENSION_ROUTES,
    FAMILY_ROUTE_PUBLICATION_INTERFACE,
    FamilyExtensionRouteCatalog,
    RouteDisposition,
    RouteKind,
    build_default_family_extension_routes,
)

TASK_ID: Final = "LFP2-044"
GOAL_ID: Final = "LFP2-G080"

_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "logic_conformance_v2"
)
_PROFILE_MANIFEST = _FIXTURE_ROOT / "profile_manifest.json"


# ---------------------------------------------------------------------------
# Interface identities
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert DEFAULT_REGISTRY_V3.interface == LOGIC_FAMILY_REGISTRY_V3_INTERFACE
    assert DEFAULT_REGISTRY_V3.interface == "LogicFamilyRegistry@3"
    assert (
        DEFAULT_PROFILE_CATALOG_V3.interface == LOGIC_PROFILE_CATALOG_V3_INTERFACE
    )
    assert DEFAULT_PROFILE_CATALOG_V3.interface == "LogicProfileCatalog@3"
    assert (
        DEFAULT_FAMILY_EXTENSION_ROUTES.publication_interface
        == FAMILY_ROUTE_PUBLICATION_INTERFACE
    )
    assert (
        DEFAULT_FAMILY_EXTENSION_ROUTES.publication_interface
        == "FamilyRoutePublication@1"
    )
    assert (
        DEFAULT_DOMAIN_FAMILY_BINDINGS.interface
        == DOMAIN_FAMILY_BINDINGS_V2_INTERFACE
    )
    assert DEFAULT_DOMAIN_FAMILY_BINDINGS.interface == "DomainFamilyBindings@2"


def test_task_and_goal_binding() -> None:
    assert DEFAULT_REGISTRY_V3.task_id == TASK_ID
    assert DEFAULT_REGISTRY_V3.goal_id == GOAL_ID
    assert DEFAULT_PROFILE_CATALOG_V3.task_id == TASK_ID
    assert DEFAULT_FAMILY_EXTENSION_ROUTES.task_id == TASK_ID
    assert DEFAULT_DOMAIN_FAMILY_BINDINGS.task_id == TASK_ID


# ---------------------------------------------------------------------------
# Registry: exact family-task coverage
# ---------------------------------------------------------------------------


def test_every_wave2_family_task_has_registry_entry() -> None:
    registry = DEFAULT_REGISTRY_V3
    assert tuple(registry.task_ids) == WAVE2_FAMILY_TASK_IDS
    for task_id in WAVE2_FAMILY_TASK_IDS:
        entries = registry.get_by_task(task_id)
        assert entries
        for entry in entries:
            assert entry.task_id == task_id
            assert entry.family_id
            assert entry.profile_ids
            assert entry.parser_module
            assert entry.semantic_identity


def test_registry_round_trip_dict() -> None:
    original = DEFAULT_REGISTRY_V3
    restored = LogicFamilyRegistryV3.from_dict(original.to_dict())
    assert restored.family_ids == original.family_ids
    assert restored.task_ids == original.task_ids
    assert restored.to_dict()["presence_implies_executability"] is False


def test_registry_presence_never_implies_executability() -> None:
    registry = DEFAULT_REGISTRY_V3
    assert registry.presence_implies_executability() is False
    payload = registry.to_dict()
    assert payload["presence_implies_executability"] is False

    # Declaration-only profiles under mu_calculus prove presence ≠ execution.
    mu = registry.get("mu_calculus")
    assert mu.family_id in registry
    assert "mu_calculus_declaration_only" in mu.profile_ids
    # Family may be parse_print executable for parse/print only.
    assert set(mu.executable_features) <= set(mu.feature_ids)
    for feature in mu.feature_ids:
        if feature not in mu.executable_features:
            assert mu.feature_is_executable(feature) is False


def test_registry_validate_against_baseline() -> None:
    registry = build_default_registry_v3(validate=True)
    registry.validate_against_baseline()
    assert len(registry) >= len(WAVE2_FAMILY_TASK_IDS)


# ---------------------------------------------------------------------------
# Profile catalog: exact profiles + fixtures + limits
# ---------------------------------------------------------------------------


def test_every_registry_profile_in_catalog() -> None:
    registry = DEFAULT_REGISTRY_V3
    catalog = DEFAULT_PROFILE_CATALOG_V3
    for family_entry in registry:
        for profile_id in family_entry.profile_ids:
            assert profile_id in catalog
            profile = catalog.get(profile_id)
            assert profile.task_id == family_entry.task_id


def test_every_executable_profile_has_fixtures_and_limits() -> None:
    catalog = DEFAULT_PROFILE_CATALOG_V3
    assert catalog.executable_profile_ids
    for profile_id in catalog.executable_profile_ids:
        entry = catalog.get(profile_id)
        assert entry.is_executable is True
        assert entry.is_declaration_only is False
        assert set(REQUIRED_FIXTURE_KINDS) <= set(entry.fixture_kinds)
        limits = entry.resource_limits
        assert limits.max_input_bytes >= 1
        assert limits.max_tokens >= 1
        assert limits.max_depth >= 1
        assert limits.max_time_ms >= 1
        assert limits.max_memory_bytes >= 1
        assert limits.max_nesting_bomb_depth <= limits.max_depth


def test_declaration_only_profile_not_executable() -> None:
    catalog = DEFAULT_PROFILE_CATALOG_V3
    decl = catalog.get("mu_calculus_declaration_only")
    assert decl.disposition is ProfileDisposition.DECLARATION_ONLY
    assert decl.is_executable is False
    assert decl.executable_features == ()
    assert catalog.presence_implies_executability() is False


def test_profile_catalog_round_trip() -> None:
    original = DEFAULT_PROFILE_CATALOG_V3
    restored = LogicProfileCatalogV3.from_dict(original.to_dict())
    assert restored.profile_ids == original.profile_ids
    assert set(restored.executable_profile_ids) == set(
        original.executable_profile_ids
    )


def test_profile_catalog_validates_against_registry() -> None:
    catalog = build_default_profile_catalog_v3(validate=True)
    catalog.validate_against_registry(DEFAULT_REGISTRY_V3)


# ---------------------------------------------------------------------------
# Family extension routes
# ---------------------------------------------------------------------------


def test_extension_routes_reviewed_feature_compatible_receipted() -> None:
    routes = DEFAULT_FAMILY_EXTENSION_ROUTES
    routes.validate_feature_compatibility()
    assert routes.presence_implies_executability() is False
    assert len(routes) >= 10

    for route in routes:
        assert route.reviewed is True
        assert route.loss_receipt.receipt_id
        assert route.loss_receipt.authority_ceiling
        assert route.owner_task_id == TASK_ID
        # Registry presence of source family never auto-admits the route.
        if route.disposition is RouteDisposition.DECLARATION_ONLY:
            assert route.is_executable is False


def test_admitted_domain_overlay_routes_exist() -> None:
    routes = DEFAULT_FAMILY_EXTENSION_ROUTES
    overlays = routes.routes_for_kind(RouteKind.DOMAIN_OVERLAY)
    assert overlays
    targets = {route.target_id for route in overlays}
    for domain in SUPPORTED_DOMAIN_IDS:
        assert domain in targets


def test_extension_routes_round_trip() -> None:
    original = DEFAULT_FAMILY_EXTENSION_ROUTES
    restored = FamilyExtensionRouteCatalog.from_dict(original.to_dict())
    assert restored.route_ids == original.route_ids


def test_provider_routes_never_grant_zk_authority() -> None:
    routes = DEFAULT_FAMILY_EXTENSION_ROUTES
    zk_block = routes.get("ext:plonk_blocks_zk_authority")
    assert zk_block.disposition is RouteDisposition.DECLARATION_ONLY
    assert zk_block.is_executable is False
    assert zk_block.loss_receipt.authority_ceiling == "none"


# ---------------------------------------------------------------------------
# Domain bindings
# ---------------------------------------------------------------------------


def test_domain_bindings_cover_all_supported_domains() -> None:
    bindings = DEFAULT_DOMAIN_FAMILY_BINDINGS
    assert set(bindings.domain_ids) == set(SUPPORTED_DOMAIN_IDS)
    bindings.validate()
    assert bindings.presence_implies_executability() is False

    for domain in SUPPORTED_DOMAIN_IDS:
        domain_bindings = bindings.bindings_for_domain(domain)
        assert domain_bindings
        for binding in domain_bindings:
            assert binding.loss_receipt.receipt_id
            assert binding.authority_ceiling
            assert binding.family_id in DEFAULT_REGISTRY_V3
            assert binding.profile_id in DEFAULT_PROFILE_CATALOG_V3


def test_domain_bindings_replace_deferred_labels() -> None:
    bindings = DEFAULT_DOMAIN_FAMILY_BINDINGS
    legal_labels = bindings.deferred_labels_for_domain("legal_ir")
    assert "argumentation" in legal_labels
    assert "description_logic" in legal_labels

    intent_labels = bindings.deferred_labels_for_domain("intent_ir")
    assert "bdi_overlay" in intent_labels
    assert "agency_overlay" in intent_labels

    crypto_labels = bindings.deferred_labels_for_domain("crypto_ir")
    assert "finite_field_constraint" in crypto_labels

    software_labels = bindings.deferred_labels_for_domain("software_verification")
    assert "session" in software_labels or "session_process" in software_labels


def test_domain_bindings_round_trip() -> None:
    original = DEFAULT_DOMAIN_FAMILY_BINDINGS
    restored = DomainFamilyBindingsV2.from_dict(original.to_dict())
    assert restored.binding_ids == original.binding_ids


def test_admitted_bindings_are_executable_only_when_receipted() -> None:
    for binding in DEFAULT_DOMAIN_FAMILY_BINDINGS:
        if binding.status is DomainBindingStatus.ADMITTED:
            assert binding.is_executable is True
            assert binding.loss_receipt.receipt_id
        if binding.status is DomainBindingStatus.DECLARATION_ONLY:
            assert binding.is_executable is False


# ---------------------------------------------------------------------------
# Profile manifest fixtures
# ---------------------------------------------------------------------------


def _load_profile_manifest() -> dict[str, Any]:
    assert _PROFILE_MANIFEST.is_file(), f"missing {_PROFILE_MANIFEST}"
    return json.loads(_PROFILE_MANIFEST.read_text(encoding="utf-8"))


def test_profile_manifest_covers_executable_profiles() -> None:
    manifest = _load_profile_manifest()
    assert manifest["task_id"] == TASK_ID
    assert manifest["goal_id"] == GOAL_ID
    assert manifest["interface"] == "LogicConformanceCorpus@2"

    profiles = manifest["profiles"]
    assert isinstance(profiles, list) and profiles
    by_id = {item["profile_id"]: item for item in profiles}

    catalog = DEFAULT_PROFILE_CATALOG_V3
    for profile_id in catalog.executable_profile_ids:
        assert profile_id in by_id, f"executable profile {profile_id} missing fixtures"
        entry = by_id[profile_id]
        fixtures = entry["fixtures"]
        for kind in REQUIRED_FIXTURE_KINDS:
            assert kind in fixtures, f"{profile_id} missing fixture kind {kind}"
        limits = entry.get("resource_limits") or {}
        assert int(limits.get("max_input_bytes", 0)) >= 1
        assert int(limits.get("max_time_ms", 0)) >= 1
        assert int(limits.get("max_depth", 0)) >= 1

    # Declaration-only profile may omit full fixture set but must appear.
    assert "mu_calculus_declaration_only" in by_id
    decl = by_id["mu_calculus_declaration_only"]
    assert decl.get("disposition") == "declaration_only"
    assert "positive" in decl["fixtures"]
    assert "negative" in decl["fixtures"]


def test_profile_manifest_profile_ids_match_catalog() -> None:
    manifest = _load_profile_manifest()
    manifest_ids = {item["profile_id"] for item in manifest["profiles"]}
    catalog_ids = set(DEFAULT_PROFILE_CATALOG_V3.profile_ids)
    assert manifest_ids == catalog_ids


def test_profile_manifest_adversarial_and_round_trip_present() -> None:
    manifest = _load_profile_manifest()
    adversarial = 0
    round_trip = 0
    for item in manifest["profiles"]:
        fixtures = item.get("fixtures") or {}
        if "adversarial" in fixtures:
            adversarial += 1
            payload = fixtures["adversarial"].get("payload", "")
            assert isinstance(payload, str) and payload
        if "round_trip" in fixtures:
            round_trip += 1
    # Every executable profile contributes both.
    assert adversarial >= len(DEFAULT_PROFILE_CATALOG_V3.executable_profile_ids)
    assert round_trip >= len(DEFAULT_PROFILE_CATALOG_V3.executable_profile_ids)


# ---------------------------------------------------------------------------
# Join coherence
# ---------------------------------------------------------------------------


def test_full_publication_join_is_coherent() -> None:
    registry = build_default_registry_v3(validate=True)
    profiles = build_default_profile_catalog_v3(validate=True, registry=registry)
    routes = build_default_family_extension_routes(validate=True)
    bindings = build_default_domain_family_bindings(validate=True)

    profiles.validate_against_registry(registry)
    routes.validate_feature_compatibility(registry=registry, profiles=profiles)
    bindings.validate(registry=registry, profiles=profiles, routes=routes)

    # Hard-zero: none of the catalogs treat presence as executability.
    assert registry.presence_implies_executability() is False
    assert profiles.presence_implies_executability() is False
    assert routes.presence_implies_executability() is False
    assert bindings.presence_implies_executability() is False


def test_family_task_profile_counts_are_exact() -> None:
    """Each Wave-2 family task contributes at least one family and profile."""

    for task_id in WAVE2_FAMILY_TASK_IDS:
        families = DEFAULT_REGISTRY_V3.get_by_task(task_id)
        profiles = DEFAULT_PROFILE_CATALOG_V3.profiles_for_task(task_id)
        assert families, task_id
        assert profiles, task_id
        # Every profile family is among the task's published families, with
        # the shared nonmonotonic/defeasible exception already encoded.
        family_ids = {entry.family_id for entry in families}
        for profile in profiles:
            if profile.profile_id == "nonmonotonic_defeasible":
                assert profile.family_id in {
                    "nonmonotonic_logic",
                    "defeasible_logic",
                }
            else:
                assert profile.family_id in family_ids


@pytest.mark.parametrize(
    "family_id",
    [
        "deontic",
        "argumentation",
        "description_logic",
        "bdi",
        "mu_calculus",
        "finite_field_constraint",
        "session_process",
    ],
)
def test_representative_families_are_published(family_id: str) -> None:
    assert family_id in DEFAULT_REGISTRY_V3
    entry = DEFAULT_REGISTRY_V3.get(family_id)
    assert entry.disposition is not FamilyLifecycleDisposition.DECLARATION_ONLY
    assert entry.profile_ids
    for profile_id in entry.profile_ids:
        assert profile_id in DEFAULT_PROFILE_CATALOG_V3
