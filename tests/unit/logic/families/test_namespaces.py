"""Contract tests for LogicIdentityNamespaces@1."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.namespaces import (
    BASELINE_NAMESPACES,
    CANONICAL_NAMESPACE_KINDS,
    IDENTITY_VERSION,
    AliasCollisionError,
    CrossNamespaceCoercionError,
    FrozenNamespaceError,
    InvalidIdentifierError,
    LogicIdentity,
    LogicIdentityNamespaces,
    NAMESPACE_INTERFACE,
    NAMESPACE_MODULE_VERSION,
    NAMESPACE_SCHEMA_VERSION,
    NamespaceBinding,
    NamespaceKind,
    SchemaVersionError,
    UnknownIdentityError,
    build_baseline_namespaces,
    coerce_identity,
    encoding_id,
    evidence_id,
    family_id,
    identity_for,
    lane_id,
    normalize_identity_name,
    notation_id,
    profile_id,
    property_id,
    provider_id,
    validate_identifier,
    view_id,
)


def test_canonical_namespace_kinds_are_complete_and_distinct() -> None:
    expected = {
        "encoding",
        "evidence",
        "family",
        "lane",
        "notation",
        "profile",
        "property",
        "provider",
        "view",
    }
    assert {kind.value for kind in CANONICAL_NAMESPACE_KINDS} == expected
    assert len(NamespaceKind) == len(expected)


def test_constructors_bind_distinct_namespaces() -> None:
    values = {
        family_id("first_order"),
        profile_id("qf_bv"),
        property_id("safety"),
        view_id("source"),
        notation_id("smt_lib2"),
        encoding_id("lean4"),
        provider_id("z3"),
        lane_id("smt"),
        evidence_id("model"),
    }
    assert len(values) == 9
    assert {item.namespace for item in values} == set(NamespaceKind)


def test_same_surface_string_is_not_interchangeable_across_namespaces() -> None:
    family = family_id("model")
    evidence = evidence_id("model")
    assert family.value == evidence.value
    assert family != evidence
    assert {family, evidence} == {family, evidence}
    assert len({family, evidence}) == 2
    assert family.qualified == "family:model"
    assert evidence.qualified == "evidence:model"

    with pytest.raises(CrossNamespaceCoercionError):
        family.coerce(NamespaceKind.EVIDENCE)
    with pytest.raises(CrossNamespaceCoercionError):
        coerce_identity(evidence, NamespaceKind.FAMILY)
    with pytest.raises(CrossNamespaceCoercionError):
        family.require("provider")
    with pytest.raises(CrossNamespaceCoercionError):
        family.as_namespace(NamespaceKind.ENCODING)


def test_same_namespace_coercion_is_identity() -> None:
    identity = provider_id("z3")
    assert identity.coerce(NamespaceKind.PROVIDER) is identity
    assert identity.require("provider") is identity
    assert coerce_identity(identity, "provider") is identity


def test_identifier_validation_rejects_malformed_values() -> None:
    with pytest.raises(InvalidIdentifierError):
        family_id("")
    with pytest.raises(InvalidIdentifierError):
        family_id(" First_Order ")
    with pytest.raises(InvalidIdentifierError):
        family_id("FirstOrder")
    with pytest.raises(InvalidIdentifierError):
        family_id("bad/id")
    with pytest.raises(InvalidIdentifierError):
        validate_identifier("has space")
    with pytest.raises(InvalidIdentifierError):
        LogicIdentity(NamespaceKind.FAMILY, "ok", version="1 0")
    with pytest.raises(InvalidIdentifierError):
        identity_for("not_a_namespace", "x")


def test_normalize_identity_name_is_collision_safe() -> None:
    assert normalize_identity_name("FOL") == "fol"
    assert normalize_identity_name("first-order") == "first_order"
    assert normalize_identity_name("  SMT LIB2 ") == "smt_lib2"
    with pytest.raises(InvalidIdentifierError):
        normalize_identity_name("???")


def test_alias_collisions_fail_closed_within_namespace() -> None:
    catalog = LogicIdentityNamespaces()
    catalog.register(
        NamespaceKind.FAMILY, "first_order", aliases=("fol", "predicate_logic")
    )

    with pytest.raises(AliasCollisionError):
        catalog.register(NamespaceKind.FAMILY, "other", aliases=("FOL",))

    with pytest.raises(AliasCollisionError):
        catalog.register(NamespaceKind.FAMILY, "fol")

    with pytest.raises(AliasCollisionError):
        NamespaceBinding(
            identity=family_id("dup"),
            aliases=("alias_a", "alias-a"),
        )

    with pytest.raises(AliasCollisionError):
        catalog.register(
            NamespaceKind.FAMILY,
            "self_collide",
            aliases=("x", "X"),
        )

    # Alias that normalizes to the canonical id collides with itself.
    with pytest.raises(AliasCollisionError):
        NamespaceBinding(
            identity=family_id("first_order"),
            aliases=("first-order",),
        )


def test_same_alias_string_may_exist_in_separate_namespaces() -> None:
    """Roles stay separate: identical surface labels do not merge namespaces."""

    catalog = LogicIdentityNamespaces()
    catalog.register(NamespaceKind.NOTATION, "smt_lib2", aliases=("smt",))
    catalog.register(NamespaceKind.LANE, "smt")
    catalog.register(NamespaceKind.ENCODING, "smt_lib2")

    assert catalog.resolve(NamespaceKind.NOTATION, "smt").value == "smt_lib2"
    assert catalog.resolve(NamespaceKind.LANE, "smt").value == "smt"
    assert catalog.resolve(NamespaceKind.ENCODING, "smt_lib2").value == "smt_lib2"

    with pytest.raises(UnknownIdentityError):
        catalog.resolve(NamespaceKind.FAMILY, "smt")
    with pytest.raises(UnknownIdentityError):
        catalog.resolve(NamespaceKind.PROVIDER, "smt_lib2")


def test_resolve_is_namespace_scoped_and_fail_closed() -> None:
    catalog = LogicIdentityNamespaces()
    catalog.register(
        NamespaceKind.PROVIDER,
        "lean",
        aliases=("lean4_provider",),
    )
    catalog.register(NamespaceKind.ENCODING, "lean4")

    assert catalog.resolve("provider", "LEAN").value == "lean"
    assert catalog.resolve(NamespaceKind.ENCODING, "lean4").namespace is NamespaceKind.ENCODING

    with pytest.raises(UnknownIdentityError):
        catalog.resolve(NamespaceKind.PROVIDER, "lean4")
    with pytest.raises(UnknownIdentityError):
        catalog.resolve(NamespaceKind.ENCODING, "lean")
    assert catalog.contains(NamespaceKind.PROVIDER, "lean4_provider")
    assert not catalog.contains(NamespaceKind.FAMILY, "lean")


def test_identity_serialization_is_deterministic_and_preserves_schema() -> None:
    identity = family_id("first_order", version="2.0.0")
    payload = identity.to_dict()
    assert list(payload) == sorted(payload)
    assert payload == {
        "interface": NAMESPACE_INTERFACE,
        "namespace": "family",
        "schema_version": NAMESPACE_SCHEMA_VERSION,
        "value": "first_order",
        "version": "2.0.0",
    }
    assert identity.to_json() == json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    assert identity.to_json() == identity.to_json()

    restored = LogicIdentity.from_dict(payload)
    assert restored == identity
    assert restored.schema_version == NAMESPACE_SCHEMA_VERSION
    assert restored.interface == NAMESPACE_INTERFACE
    assert restored.version == "2.0.0"

    round_trip = LogicIdentity.parse(identity.to_json())
    assert round_trip == identity


def test_identity_parse_rejects_wrong_schema_or_interface() -> None:
    with pytest.raises(SchemaVersionError):
        LogicIdentity.from_dict(
            {
                "interface": NAMESPACE_INTERFACE,
                "namespace": "family",
                "schema_version": "logic-identity-namespaces/v0",
                "value": "first_order",
                "version": IDENTITY_VERSION,
            }
        )
    with pytest.raises(SchemaVersionError):
        LogicIdentity.from_dict(
            {
                "interface": "OtherInterface@9",
                "namespace": "family",
                "schema_version": NAMESPACE_SCHEMA_VERSION,
                "value": "first_order",
                "version": IDENTITY_VERSION,
            }
        )


def test_catalog_serialization_is_deterministic_and_round_trips() -> None:
    catalog = LogicIdentityNamespaces(version="9.9.9")
    catalog.register(NamespaceKind.PROPERTY, "safety", aliases=("safe",), name="Safety")
    catalog.register(NamespaceKind.PROVIDER, "z3", name="Z3")
    catalog.register(NamespaceKind.FAMILY, "temporal")
    catalog.freeze()

    first = catalog.to_dict()
    second = catalog.to_dict()
    assert first == second
    assert first["schema_version"] == NAMESPACE_SCHEMA_VERSION
    assert first["interface"] == NAMESPACE_INTERFACE
    assert first["version"] == "9.9.9"
    namespaces = [row["namespace"] for row in first["bindings"]]
    values = [row["value"] for row in first["bindings"]]
    assert namespaces == sorted(namespaces)
    # Within a namespace, values are sorted.
    by_ns: dict[str, list[str]] = {}
    for row in first["bindings"]:
        by_ns.setdefault(row["namespace"], []).append(row["value"])
    for items in by_ns.values():
        assert items == sorted(items)

    json_a = catalog.to_json()
    json_b = catalog.to_json()
    assert json_a == json_b
    assert json.loads(json_a) == first

    restored = LogicIdentityNamespaces.from_dict(first, frozen=True)
    assert restored.to_dict() == first
    assert restored.version == "9.9.9"
    assert restored.resolve(NamespaceKind.PROPERTY, "safe").value == "safety"
    assert restored.frozen is True

    parsed = LogicIdentityNamespaces.parse(json_a, frozen=True)
    assert parsed.to_dict() == first


def test_catalog_parse_rejects_wrong_schema() -> None:
    with pytest.raises(SchemaVersionError):
        LogicIdentityNamespaces.from_dict(
            {
                "bindings": [],
                "interface": NAMESPACE_INTERFACE,
                "schema_version": "nope",
                "version": NAMESPACE_MODULE_VERSION,
            }
        )


def test_binding_namespace_disagreement_fails_closed() -> None:
    with pytest.raises(CrossNamespaceCoercionError):
        NamespaceBinding.from_dict(
            {
                "aliases": [],
                "identity": family_id("first_order").to_dict(),
                "namespace": "provider",
                "value": "first_order",
            }
        )


def test_identities_are_immutable() -> None:
    identity = view_id("source")
    with pytest.raises(FrozenInstanceError):
        identity.value = "other"  # type: ignore[misc]
    binding = NamespaceBinding(identity=identity, aliases=("src",))
    with pytest.raises(FrozenInstanceError):
        binding.aliases = ()  # type: ignore[misc]


def test_frozen_catalog_rejects_mutation() -> None:
    catalog = LogicIdentityNamespaces(frozen=True)
    with pytest.raises(FrozenNamespaceError):
        catalog.register(NamespaceKind.FAMILY, "first_order")


def test_require_identity_checks_registration_and_version() -> None:
    catalog = LogicIdentityNamespaces()
    catalog.register(NamespaceKind.LANE, "atp", version="1.0.0")
    registered = lane_id("atp", version="1.0.0")
    assert catalog.require_identity(registered, NamespaceKind.LANE) == registered

    with pytest.raises(UnknownIdentityError):
        catalog.require_identity(lane_id("smt"))
    with pytest.raises(CrossNamespaceCoercionError):
        catalog.require_identity(registered, NamespaceKind.PROVIDER)
    with pytest.raises(SchemaVersionError):
        catalog.require_identity(lane_id("atp", version="2.0.0"))
    with pytest.raises(CrossNamespaceCoercionError):
        catalog.coerce(family_id("first_order"), NamespaceKind.LANE)


def test_baseline_namespaces_cover_required_roles() -> None:
    catalog = BASELINE_NAMESPACES
    assert catalog.frozen is True
    assert catalog.schema_version == NAMESPACE_SCHEMA_VERSION
    assert catalog.interface == NAMESPACE_INTERFACE
    assert catalog.version == NAMESPACE_MODULE_VERSION

    # One representative per required plan namespace.
    assert catalog.resolve(NamespaceKind.FAMILY, "fol").value == "first_order"
    assert catalog.resolve(NamespaceKind.PROFILE, "hyperltl").namespace is NamespaceKind.PROFILE
    assert catalog.resolve(NamespaceKind.PROPERTY, "safety").value == "safety"
    assert catalog.resolve(NamespaceKind.VIEW, "vc").value == "verification_condition"
    assert catalog.resolve(NamespaceKind.NOTATION, "smt").value == "smt_lib2"
    assert catalog.resolve(NamespaceKind.ENCODING, "lean4").value == "lean4"
    assert catalog.resolve(NamespaceKind.PROVIDER, "z3").value == "z3"
    assert catalog.resolve(NamespaceKind.LANE, "runtime").value == "runtime_monitor"
    assert catalog.resolve(NamespaceKind.EVIDENCE, "kernel_checked_proof").value == (
        "kernel_checked_proof"
    )

    # Cross-namespace misuse of baseline labels fails closed.
    with pytest.raises(UnknownIdentityError):
        catalog.resolve(NamespaceKind.FAMILY, "z3")
    with pytest.raises(UnknownIdentityError):
        catalog.resolve(NamespaceKind.FAMILY, "safety")
    with pytest.raises(UnknownIdentityError):
        catalog.resolve(NamespaceKind.PROVIDER, "first_order")
    with pytest.raises(CrossNamespaceCoercionError):
        coerce_identity(
            catalog.resolve(NamespaceKind.PROVIDER, "lean"),
            NamespaceKind.FAMILY,
        )

    rebuilt = build_baseline_namespaces(frozen=True)
    assert rebuilt.to_dict() == catalog.to_dict()
    assert rebuilt.to_json() == catalog.to_json()


def test_baseline_has_no_internal_alias_collisions() -> None:
    """Re-registering baseline bindings into a fresh catalog must succeed."""

    fresh = LogicIdentityNamespaces()
    for binding in BASELINE_NAMESPACES:
        fresh.register_binding(binding)
    assert len(fresh) == len(BASELINE_NAMESPACES)
    assert {item.namespace for item in fresh.identities()} == set(NamespaceKind)


def test_catalog_membership_and_iteration_are_deterministic() -> None:
    catalog = LogicIdentityNamespaces()
    catalog.register(NamespaceKind.EVIDENCE, "model")
    catalog.register(NamespaceKind.FAMILY, "modal")
    identity = evidence_id("model")
    assert identity in catalog
    assert family_id("modal") in catalog
    assert provider_id("model") not in catalog

    ordered = list(catalog)
    assert [item.namespace.value for item in ordered] == ["evidence", "family"]
    assert catalog.identities(NamespaceKind.FAMILY) == (family_id("modal"),)
