"""Catalog drift tests for CanonicalLogicCatalogSnapshot@1 (LPC-021).

Acceptance (fail closed):

* aliases
* namespace coercion
* profile/family references
* provider operations
* executable-vs-declared features
* authority ceilings
* catalog-root reproducibility

These tests import the sealed composition root and prove that layer drift,
identity misuse, and authority inflation raise rather than silently admit.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.families.aliases import (
    AliasCollisionError,
    BASELINE_ALIAS_REGISTRY,
    FrozenAliasRegistryError,
    LogicAliasRegistry,
    UnknownAliasError,
    WrongNamespaceError,
)
from ipfs_datasets_py.logic.families.canonical_catalog import (
    CANONICAL_CATALOG_IDENTITY_DOMAIN,
    CANONICAL_CATALOG_SNAPSHOT_INTERFACE,
    DEFAULT_CANONICAL_CATALOG_SNAPSHOT,
    CanonicalLogicCatalogSnapshot,
    CatalogCompositionError,
    UnknownCatalogIdentityError,
    build_canonical_logic_catalog_snapshot,
)
from ipfs_datasets_py.logic.families.models import (
    EvidenceAuthority,
    FamilySupportDescriptor,
    SupportLevel,
)
from ipfs_datasets_py.logic.families.namespaces import (
    CrossNamespaceCoercionError,
    NamespaceKind,
    UnknownIdentityError,
    family_id,
    provider_id,
)
from ipfs_datasets_py.logic.families.profile_catalog_v3 import (
    DEFAULT_EXECUTABLE_FEATURES,
    DEFAULT_PROFILE_CATALOG_V3,
    DEFAULT_RESOURCE_LIMITS,
    LogicProfileCatalogV3,
    ProfileCatalogEntryV3,
    ProfileCatalogV3Error,
    ProfileDisposition,
    REQUIRED_FIXTURE_KINDS,
)
from ipfs_datasets_py.logic.families.providers import (
    ADVISORY_AUTHORITY_CEILINGS,
    BASELINE_PROVIDER_CATALOG,
    ProviderCapabilityCatalog,
    ProviderCapabilityEntry,
    ProviderCatalogAuthorityError,
    ProviderCatalogDriftError,
)
from ipfs_datasets_py.logic.families.registry import (
    InvalidCapabilityError,
)
from ipfs_datasets_py.logic.families.registry_v3 import (
    DEFAULT_REGISTRY_V3,
    FamilyLifecycleDisposition,
    FamilyPublicationEntry,
    FamilyPublicationError,
)
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity


# ---------------------------------------------------------------------------
# Snapshot surface
# ---------------------------------------------------------------------------


def test_default_snapshot_is_sealed_composition_root() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    assert snapshot.interface == CANONICAL_CATALOG_SNAPSHOT_INTERFACE
    assert snapshot.aliases is BASELINE_ALIAS_REGISTRY
    assert snapshot.providers is BASELINE_PROVIDER_CATALOG
    assert snapshot.profiles is DEFAULT_PROFILE_CATALOG_V3
    assert snapshot.publication is DEFAULT_REGISTRY_V3
    snapshot.validate()


# ---------------------------------------------------------------------------
# Aliases fail closed
# ---------------------------------------------------------------------------


def test_alias_unknown_and_wrong_namespace_fail_closed_on_snapshot() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    aliases = snapshot.aliases

    with pytest.raises(UnknownAliasError):
        aliases.resolve(NamespaceKind.FAMILY, "not_a_real_family_zzzz")

    # Notation label cannot be resolved as a family.
    with pytest.raises(WrongNamespaceError):
        aliases.resolve(NamespaceKind.FAMILY, "smt")

    # Property / profile / provider labels are not families.
    for label in ("safety", "hyperltl", "lean", "z3"):
        with pytest.raises(WrongNamespaceError):
            aliases.resolve(NamespaceKind.FAMILY, label)

    diagnostic = aliases.diagnose(NamespaceKind.FAMILY, "smt")
    assert not diagnostic.ok
    assert diagnostic.resolved is None
    assert diagnostic.error_code == "wrong_namespace"


def test_alias_collisions_and_non_canonical_writes_fail_closed() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    aliases = snapshot.aliases

    # Dual-read accepts the legacy surface form; one-write emits only canonical.
    identity = aliases.resolve(NamespaceKind.FAMILY, "fol")
    assert identity.value == "first_order"
    assert aliases.write_value(NamespaceKind.FAMILY, "fol") == "first_order"

    # Sealed baseline cannot be mutated in place.
    with pytest.raises(FrozenAliasRegistryError):
        aliases.register(
            "fol",
            "program",
            namespace=NamespaceKind.FAMILY,
        )

    # Collision: rebinding an existing alias surface to a different target.
    mutable = LogicAliasRegistry(
        namespaces=snapshot.namespaces,
        frozen=False,
    )
    mutable.register("legacy_fol", "first_order", namespace=NamespaceKind.FAMILY)
    with pytest.raises(AliasCollisionError):
        mutable.register(
            "legacy_fol",
            "program",
            namespace=NamespaceKind.FAMILY,
        )
    with pytest.raises(AliasCollisionError):
        mutable.register(
            "fol",
            "program",
            namespace=NamespaceKind.FAMILY,
        )

    # Unknown labels cannot be written.
    with pytest.raises(UnknownAliasError):
        aliases.write_value(NamespaceKind.FAMILY, "ghost_family_zzzz")


# ---------------------------------------------------------------------------
# Namespace coercion fails closed
# ---------------------------------------------------------------------------


def test_namespace_coercion_fails_closed_across_roles() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    namespaces = snapshot.namespaces

    family = namespaces.resolve(NamespaceKind.FAMILY, "first_order")
    provider = namespaces.resolve(NamespaceKind.PROVIDER, "z3")

    with pytest.raises(CrossNamespaceCoercionError):
        family.require(NamespaceKind.PROVIDER)
    with pytest.raises(CrossNamespaceCoercionError):
        family.coerce(NamespaceKind.PROFILE)
    with pytest.raises(CrossNamespaceCoercionError):
        provider.require(NamespaceKind.FAMILY)
    with pytest.raises(CrossNamespaceCoercionError):
        provider_id("z3").as_namespace(NamespaceKind.LANE)

    # Same surface string in different roles never merges.
    model_family = family_id("model")
    model_evidence = namespaces.resolve(NamespaceKind.EVIDENCE, "model")
    assert model_family.value == model_evidence.value
    assert model_family != model_evidence
    with pytest.raises(CrossNamespaceCoercionError):
        model_family.coerce(NamespaceKind.EVIDENCE)

    # Unknown identities fail closed inside the requested role only.
    with pytest.raises(UnknownIdentityError):
        namespaces.resolve(NamespaceKind.FAMILY, "not_registered_zzzz")
    with pytest.raises(UnknownIdentityError):
        namespaces.resolve(NamespaceKind.PROVIDER, "first_order")


# ---------------------------------------------------------------------------
# Profile / family references fail closed
# ---------------------------------------------------------------------------


def _replace_profile(
    entry: ProfileCatalogEntryV3,
    **changes: object,
) -> ProfileCatalogEntryV3:
    payload = entry.to_dict()
    payload.update(changes)
    return ProfileCatalogEntryV3.from_dict(payload)


def _profiles_with(entry: ProfileCatalogEntryV3) -> LogicProfileCatalogV3:
    others = tuple(
        item
        for item in DEFAULT_PROFILE_CATALOG_V3.entries
        if item.profile_id != entry.profile_id
    )
    return LogicProfileCatalogV3(entries=others + (entry,))


def _owned_profile_pair(
    snapshot: CanonicalLogicCatalogSnapshot,
) -> tuple[str, ProfileCatalogEntryV3]:
    """Return a profile that is not the shared nonmonotonic_defeasible exception."""

    for family_entry in snapshot.publication.entries:
        for profile_id in family_entry.profile_ids:
            if profile_id == "nonmonotonic_defeasible":
                continue
            original = snapshot.profiles.get(profile_id)
            if original.family_id == family_entry.family_id:
                return profile_id, original
    raise AssertionError("no exclusively owned publication profile found")


def test_profile_family_mismatch_fails_closed() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    _profile_id, original = _owned_profile_pair(snapshot)

    # Point the profile at a different published family.
    other_family = next(
        item.family_id
        for item in snapshot.publication.entries
        if item.family_id != original.family_id
        and item.family_id not in {"defeasible_logic", "nonmonotonic_logic"}
    )
    drifted = _replace_profile(original, family_id=other_family)
    drifted_catalog = _profiles_with(drifted)

    with pytest.raises(ProfileCatalogV3Error, match="family mismatch"):
        drifted_catalog.validate_against_registry(snapshot.publication)

    with pytest.raises(ProfileCatalogV3Error, match="family mismatch"):
        build_canonical_logic_catalog_snapshot(
            profiles=drifted_catalog,
            validate=True,
        )


def test_missing_registry_profile_reference_fails_closed() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    family_entry = next(
        item for item in snapshot.publication.entries if item.profile_ids
    )
    missing_id = family_entry.profile_ids[0]
    reduced = LogicProfileCatalogV3(
        entries=tuple(
            item
            for item in snapshot.profiles.entries
            if item.profile_id != missing_id
        )
    )

    with pytest.raises(ProfileCatalogV3Error, match="missing from profile catalog"):
        reduced.validate_against_registry(snapshot.publication)

    with pytest.raises(ProfileCatalogV3Error, match="missing from profile catalog"):
        build_canonical_logic_catalog_snapshot(profiles=reduced, validate=True)


def test_profile_task_mismatch_fails_closed() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    family_entry = next(
        item for item in snapshot.publication.entries if item.profile_ids
    )
    profile_id = family_entry.profile_ids[0]
    original = snapshot.profiles.get(profile_id)
    # Choose a different Wave-2 task id than the owning family.
    other_task = next(
        task
        for task in snapshot.publication.task_ids
        if task != original.task_id
    )
    drifted = _replace_profile(original, task_id=other_task)
    drifted_catalog = _profiles_with(drifted)

    with pytest.raises(ProfileCatalogV3Error, match="task mismatch"):
        drifted_catalog.validate_against_registry(snapshot.publication)


def test_profile_for_unpublished_family_fails_closed() -> None:
    ghost = ProfileCatalogEntryV3(
        profile_id="ghost_profile_for_unpublished_family",
        family_id="not_a_published_family_zzzz",
        task_id="LFP2-037",
        disposition=ProfileDisposition.PARSE_PRINT,
        feature_ids=DEFAULT_EXECUTABLE_FEATURES,
        executable_features=DEFAULT_EXECUTABLE_FEATURES,
        resource_limits=DEFAULT_RESOURCE_LIMITS,
        fixture_kinds=REQUIRED_FIXTURE_KINDS,
    )
    # Keep every published profile so the unpublished-family check is reached.
    extended = LogicProfileCatalogV3(
        entries=DEFAULT_PROFILE_CATALOG_V3.entries + (ghost,)
    )
    with pytest.raises(ProfileCatalogV3Error, match="not published in registry"):
        extended.validate_against_registry(DEFAULT_REGISTRY_V3)


# ---------------------------------------------------------------------------
# Provider operations fail closed
# ---------------------------------------------------------------------------


def test_provider_operations_outside_family_fail_closed() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    # first_order does not expose the pdr operation (horn_chc does).
    overclaim = ProviderCapabilityEntry(
        provider_id="z3",
        provider_version="drift-v1",
        authority_ceiling=EvidenceAuthority.BOUNDED,
        family_support=(
            FamilySupportDescriptor(
                "first_order",
                SupportLevel.NATIVE,
                operation_ids=("pdr",),
            ),
        ),
        in_executable_matrix=True,
    )
    with pytest.raises(InvalidCapabilityError, match="outside family"):
        snapshot.taxonomy.validate_provider_capability(
            overclaim.to_capability_descriptor()
        )


def test_provider_unknown_family_and_profile_promotion_fail_closed() -> None:
    with pytest.raises(ProviderCatalogDriftError, match="outside the baseline"):
        ProviderCapabilityEntry(
            provider_id="z3",
            provider_version="drift-v1",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            family_support=(
                FamilySupportDescriptor(
                    "not_a_real_family_zzzz",
                    SupportLevel.NATIVE,
                ),
            ),
            in_executable_matrix=True,
        )

    with pytest.raises(ProviderCatalogDriftError, match="non-family profile"):
        ProviderCapabilityEntry(
            provider_id="z3",
            provider_version="drift-v1",
            authority_ceiling=EvidenceAuthority.BOUNDED,
            family_support=(
                FamilySupportDescriptor("dynamic_logic", SupportLevel.NATIVE),
            ),
            in_executable_matrix=True,
        )


def test_provider_declaration_only_family_cannot_gain_executable_ops() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    # mu_calculus is declaration-only in the taxonomy.
    assert snapshot.taxonomy.families["mu_calculus"].declaration_only
    overclaim = ProviderCapabilityEntry(
        provider_id="z3",
        provider_version="drift-v1",
        authority_ceiling=EvidenceAuthority.BOUNDED,
        family_support=(
            FamilySupportDescriptor("mu_calculus", SupportLevel.NATIVE),
        ),
        in_executable_matrix=True,
    )
    with pytest.raises(InvalidCapabilityError, match="declaration-only"):
        snapshot.taxonomy.validate_provider_capability(
            overclaim.to_capability_descriptor()
        )

    catalog = ProviderCapabilityCatalog(frozen=False)
    catalog.register(overclaim)
    # Catalog join validation fails closed on the same overclaim (taxonomy path).
    with pytest.raises(InvalidCapabilityError, match="declaration-only"):
        catalog.validate_against_registry(snapshot.taxonomy)


def test_snapshot_provider_matrix_join_stays_closed() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    snapshot.providers.validate_executable_matrix_join()
    snapshot.providers.validate_against_registry(snapshot.taxonomy)
    snapshot.matrix.validate_against_catalog(snapshot.providers)


# ---------------------------------------------------------------------------
# Executable-vs-declared features fail closed
# ---------------------------------------------------------------------------


def test_declaration_only_cannot_claim_executable_features() -> None:
    with pytest.raises(FamilyPublicationError, match="cannot claim"):
        FamilyPublicationEntry(
            family_id="ghost_decl",
            task_id="LFP2-037",
            name="Ghost Declaration",
            disposition=FamilyLifecycleDisposition.DECLARATION_ONLY,
            profile_ids=("ghost_profile",),
            feature_ids=("parse", "print"),
            executable_features=("parse",),
        )

    with pytest.raises(ProfileCatalogV3Error, match="cannot claim"):
        ProfileCatalogEntryV3(
            profile_id="ghost_decl_profile",
            family_id="ghost_decl",
            task_id="LFP2-037",
            disposition=ProfileDisposition.DECLARATION_ONLY,
            feature_ids=("parse", "print"),
            executable_features=("parse",),
        )


def test_executable_features_must_be_declared() -> None:
    with pytest.raises(FamilyPublicationError, match="not in feature_ids"):
        FamilyPublicationEntry(
            family_id="ghost_exec",
            task_id="LFP2-037",
            name="Ghost Executable",
            disposition=FamilyLifecycleDisposition.CONTROLLED_EXECUTABLE,
            profile_ids=("ghost_profile",),
            feature_ids=("parse", "print"),
            executable_features=("parse", "model_check"),
        )

    with pytest.raises(ProfileCatalogV3Error, match="not in feature_ids"):
        ProfileCatalogEntryV3(
            profile_id="ghost_exec_profile",
            family_id="ghost_exec",
            task_id="LFP2-037",
            disposition=ProfileDisposition.CONTROLLED_EXECUTABLE,
            feature_ids=("parse", "print"),
            executable_features=("parse", "model_check"),
            resource_limits=DEFAULT_RESOURCE_LIMITS,
            fixture_kinds=REQUIRED_FIXTURE_KINDS,
        )


def test_controlled_executable_requires_explicit_features() -> None:
    with pytest.raises(FamilyPublicationError, match="must list"):
        FamilyPublicationEntry(
            family_id="ghost_empty_exec",
            task_id="LFP2-037",
            name="Ghost Empty Exec",
            disposition=FamilyLifecycleDisposition.CONTROLLED_EXECUTABLE,
            profile_ids=("ghost_profile",),
            feature_ids=("parse", "print"),
            executable_features=(),
        )

    with pytest.raises(ProfileCatalogV3Error, match="must list"):
        ProfileCatalogEntryV3(
            profile_id="ghost_empty_exec_profile",
            family_id="ghost_empty_exec",
            task_id="LFP2-037",
            disposition=ProfileDisposition.PARSE_PRINT,
            feature_ids=("parse", "print"),
            executable_features=(),
        )


def test_declared_features_are_not_all_executable_on_snapshot() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    # Presence never upgrades declaration to executability.
    assert snapshot.presence_implies_executability() is False
    assert snapshot.publication.presence_implies_executability() is False
    assert snapshot.profiles.presence_implies_executability() is False

    for entry in snapshot.publication.entries:
        if entry.disposition is FamilyLifecycleDisposition.DECLARATION_ONLY:
            assert not entry.is_executable
            assert entry.executable_features == ()
            assert snapshot.claims_executability(entry.family_id) is False
        else:
            # Every declared feature is not automatically executable.
            for feature in entry.feature_ids:
                if feature not in entry.executable_features:
                    assert entry.feature_is_executable(feature) is False
            for feature in entry.executable_features:
                assert entry.claims_feature(feature)
                assert entry.feature_is_executable(feature) is True

    for profile in snapshot.profiles.entries:
        for feature in profile.feature_ids:
            if feature not in profile.executable_features:
                assert profile.feature_is_executable(feature) is False


# ---------------------------------------------------------------------------
# Authority ceilings fail closed
# ---------------------------------------------------------------------------


def test_advisory_provider_authority_ceilings_fail_closed() -> None:
    assert ADVISORY_AUTHORITY_CEILINGS
    for provider_id_value, ceiling in ADVISORY_AUTHORITY_CEILINGS.items():
        entry = DEFAULT_CANONICAL_CATALOG_SNAPSHOT.providers.get(provider_id_value)
        assert entry.advisory is True
        assert entry.authority_ceiling is ceiling
        assert entry.authority_ceiling is EvidenceAuthority.ADVISORY

    with pytest.raises(ProviderCatalogAuthorityError, match="hard ceiling|above advisory"):
        ProviderCapabilityEntry(
            provider_id="symbolicai",
            provider_version="drift-v1",
            authority_ceiling=EvidenceAuthority.AUTHORITATIVE,
            family_support=(),
            advisory=True,
            in_executable_matrix=False,
        )

    with pytest.raises(ProviderCatalogAuthorityError, match="authoritative evidence"):
        ProviderCapabilityEntry(
            provider_id="hammer",
            provider_version="drift-v1",
            authority_ceiling=EvidenceAuthority.ADVISORY,
            family_support=(),
            evidence_ids=("kernel_checked_proof",),
            advisory=True,
            in_executable_matrix=True,
        )


def test_publication_and_profile_authority_ceilings_are_closed_identifiers() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    allowed = {
        "none",
        "advisory",
        "bounded",
        "independently_checkable",
        "authoritative",
    }
    for entry in snapshot.publication.entries:
        assert entry.authority_ceiling in allowed
        # Catalog presence never grants production admission regardless of ceiling.
        assert snapshot.is_production_admitted(entry.family_id) is False

    for profile in snapshot.profiles.entries:
        assert profile.authority_ceiling in allowed

    with pytest.raises(FamilyPublicationError):
        FamilyPublicationEntry(
            family_id="ghost_ceiling",
            task_id="LFP2-037",
            name="Ghost Ceiling",
            disposition=FamilyLifecycleDisposition.DECLARATION_ONLY,
            profile_ids=("ghost_profile",),
            authority_ceiling="proof of everything",  # whitespace / free text
        )


def test_unknown_family_authority_queries_fail_closed() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    with pytest.raises(UnknownCatalogIdentityError):
        snapshot.publication_stage("not_a_real_family_zzzz")
    with pytest.raises(UnknownCatalogIdentityError):
        snapshot.is_production_admitted("not_a_real_family_zzzz")
    assert snapshot.claims_executability("not_a_real_family_zzzz") is False


# ---------------------------------------------------------------------------
# Catalog-root reproducibility
# ---------------------------------------------------------------------------


def test_catalog_root_is_reproducible_across_rebuilds() -> None:
    first = build_canonical_logic_catalog_snapshot(validate=True)
    second = build_canonical_logic_catalog_snapshot(validate=True)
    sealed = DEFAULT_CANONICAL_CATALOG_SNAPSHOT

    assert first.content_root == second.content_root == sealed.content_root
    assert first.content_digest == second.content_digest == sealed.content_digest
    assert first.content_digest.startswith("sha256:")
    assert first.content_root.startswith("b")

    recomputed = canonical_identity(
        first.layer_envelope(),
        domain=CANONICAL_CATALOG_IDENTITY_DOMAIN,
        schema_version=first.schema_version,
    )
    assert recomputed.cid == first.content_root
    assert recomputed.digest == first.content_digest


def test_layer_content_drift_changes_catalog_root() -> None:
    sealed = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    envelope = sealed.layer_envelope()
    assert envelope["interface"] == CANONICAL_CATALOG_SNAPSHOT_INTERFACE

    mutated = dict(envelope)
    mutated["notes"] = (mutated.get("notes") or "") + "\n# catalog-root drift probe"
    drifted = canonical_identity(
        mutated,
        domain=CANONICAL_CATALOG_IDENTITY_DOMAIN,
        schema_version=sealed.schema_version,
    )
    assert drifted.cid != sealed.content_root
    assert drifted.digest != sealed.content_digest

    # Construct a sibling with different notes; content root must diverge.
    sibling = CanonicalLogicCatalogSnapshot(
        taxonomy=sealed.taxonomy,
        namespaces=sealed.namespaces,
        aliases=sealed.aliases,
        publication=sealed.publication,
        profiles=sealed.profiles,
        providers=sealed.providers,
        matrix=sealed.matrix,
        generated=sealed.generated,
        notes=sealed.notes + "\n# alternate composition notes",
    )
    assert sibling.content_root != sealed.content_root
    assert sibling.content_digest != sealed.content_digest
    # validate still passes: notes drift is identity-relevant, not integrity-breaking
    sibling.validate()


def test_composition_integrity_rejects_presence_as_executability() -> None:
    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    assert snapshot.presence_implies_executability() is False
    assert snapshot.presence_implies_production_admission() is False

    # Controlled-executable families must list executable features or composition fails.
    for family_id_value in snapshot.publication.executable_family_ids:
        entry = snapshot.publication.get(family_id_value)
        assert entry.executable_features
        assert snapshot.claims_executability(family_id_value) is True


def test_composition_fails_closed_when_profile_layer_drifts() -> None:
    """End-to-end: drifted profile layer cannot seal a validated snapshot."""

    snapshot = DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    _profile_id, original = _owned_profile_pair(snapshot)
    other_family = next(
        item.family_id
        for item in snapshot.publication.entries
        if item.family_id
        not in {original.family_id, "defeasible_logic", "nonmonotonic_logic"}
    )
    drifted_catalog = _profiles_with(
        _replace_profile(original, family_id=other_family)
    )

    with pytest.raises((ProfileCatalogV3Error, CatalogCompositionError)):
        build_canonical_logic_catalog_snapshot(
            profiles=drifted_catalog,
            validate=True,
        )
