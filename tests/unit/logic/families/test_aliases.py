"""Contract tests for LogicAliasRegistry@1 and LogicMigrationDiagnostic@1."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from ipfs_datasets_py.logic.families.aliases import (
    ALIAS_INTERFACE,
    ALIAS_MODULE_VERSION,
    ALIAS_SCHEMA_VERSION,
    BASELINE_ALIAS_REGISTRY,
    DIAGNOSTIC_INTERFACE,
    DIAGNOSTIC_SCHEMA_VERSION,
    AliasCollisionError,
    AliasCycleError,
    AliasEdge,
    AliasError,
    AliasResolutionKind,
    FrozenAliasRegistryError,
    LogicAliasRegistry,
    LogicMigrationDiagnostic,
    MigrationDisposition,
    UnknownAliasError,
    WrongNamespaceError,
    build_baseline_alias_registry,
    canonicalize_label,
    dual_read,
    one_write,
)
from ipfs_datasets_py.logic.families.namespaces import (
    InvalidIdentifierError,
    LogicIdentityNamespaces,
    NamespaceKind,
    SchemaVersionError,
    family_id,
    provider_id,
)


def _mutable_namespaces() -> LogicIdentityNamespaces:
    catalog = LogicIdentityNamespaces()
    catalog.register(NamespaceKind.FAMILY, "first_order", aliases=("fol",))
    catalog.register(NamespaceKind.FAMILY, "program")
    catalog.register(NamespaceKind.FAMILY, "transition_system")
    catalog.register(NamespaceKind.FAMILY, "hyperproperty")
    catalog.register(NamespaceKind.FAMILY, "cryptographic_protocol")
    catalog.register(NamespaceKind.FAMILY, "authorization")
    catalog.register(NamespaceKind.PROFILE, "hyperltl")
    catalog.register(NamespaceKind.PROFILE, "tla_plus", aliases=("tla+",))
    catalog.register(NamespaceKind.PROFILE, "secpal")
    catalog.register(NamespaceKind.PROPERTY, "safety")
    catalog.register(NamespaceKind.PROPERTY, "liveness")
    catalog.register(NamespaceKind.PROPERTY, "noninterference")
    catalog.register(NamespaceKind.PROPERTY, "satisfiability")
    catalog.register(NamespaceKind.VIEW, "verification_condition", aliases=("vc",))
    catalog.register(NamespaceKind.VIEW, "graph_projection")
    catalog.register(NamespaceKind.NOTATION, "smt_lib2", aliases=("smt", "smtlib2", "smt_lib"))
    catalog.register(NamespaceKind.PROVIDER, "z3")
    catalog.register(NamespaceKind.PROVIDER, "proverif")
    catalog.register(NamespaceKind.PROVIDER, "tamarin")
    catalog.register(NamespaceKind.PROVIDER, "lean")
    catalog.register(NamespaceKind.PROVIDER, "rocq", aliases=("coq",))
    catalog.register(NamespaceKind.PROVIDER, "isabelle")
    catalog.register(NamespaceKind.LANE, "runtime_monitor", aliases=("runtime",))
    catalog.register(NamespaceKind.EVIDENCE, "kernel_checked_proof")
    return catalog


def test_interfaces_and_schema_versions() -> None:
    assert BASELINE_ALIAS_REGISTRY.interface == ALIAS_INTERFACE
    assert BASELINE_ALIAS_REGISTRY.schema_version == ALIAS_SCHEMA_VERSION
    assert BASELINE_ALIAS_REGISTRY.version == ALIAS_MODULE_VERSION

    identity, diagnostic = dual_read(NamespaceKind.FAMILY, "fol")
    assert identity.value == "first_order"
    assert diagnostic.interface == DIAGNOSTIC_INTERFACE
    assert diagnostic.schema_version == DIAGNOSTIC_SCHEMA_VERSION


def test_dual_read_fol_to_first_order() -> None:
    identity, diagnostic = BASELINE_ALIAS_REGISTRY.read(NamespaceKind.FAMILY, "fol")
    assert identity == family_id("first_order")
    assert diagnostic.ok
    assert diagnostic.was_alias
    assert diagnostic.disposition is MigrationDisposition.REPLACED
    assert diagnostic.replacement == "first_order"
    assert diagnostic.alias_path[-1] == "first_order"

    # Case / separator variants normalize through the namespace catalog.
    assert BASELINE_ALIAS_REGISTRY.resolve("family", "FOL").value == "first_order"
    assert BASELINE_ALIAS_REGISTRY.resolve("family", "predicate_logic").value == (
        "first_order"
    )


def test_plan_evidence_cases_dual_read() -> None:
    """Cover the plan evidence subset: fol/smt/tla_plus/hyperltl/protocol/secpal/VC/safety/provider/view."""

    registry = BASELINE_ALIAS_REGISTRY

    assert registry.resolve(NamespaceKind.FAMILY, "fol").value == "first_order"
    assert registry.resolve(NamespaceKind.NOTATION, "smt").value == "smt_lib2"
    assert registry.resolve(NamespaceKind.NOTATION, "smtlib2").value == "smt_lib2"
    assert registry.resolve(NamespaceKind.NOTATION, "smt_lib").value == "smt_lib2"
    assert registry.resolve(NamespaceKind.PROFILE, "tla_plus").value == "tla_plus"
    assert registry.resolve(NamespaceKind.PROFILE, "tla+").value == "tla_plus"
    assert registry.resolve(NamespaceKind.PROFILE, "hyperltl").value == "hyperltl"
    assert registry.resolve(NamespaceKind.FAMILY, "protocol").value == (
        "cryptographic_protocol"
    )
    assert registry.resolve(NamespaceKind.PROFILE, "secpal").value == "secpal"
    assert registry.resolve(NamespaceKind.PROFILE, "policy").value == "secpal"
    assert registry.resolve(NamespaceKind.VIEW, "VC").value == "verification_condition"
    assert registry.resolve(NamespaceKind.VIEW, "verification_condition").value == (
        "verification_condition"
    )
    assert registry.resolve(NamespaceKind.PROPERTY, "safety").value == "safety"
    assert registry.resolve(NamespaceKind.PROPERTY, "liveness").value == "liveness"
    assert registry.resolve(NamespaceKind.PROVIDER, "z3").value == "z3"
    assert registry.resolve(NamespaceKind.PROVIDER, "proverif").value == "proverif"
    assert registry.resolve(NamespaceKind.PROVIDER, "lean").value == "lean"
    assert registry.resolve(NamespaceKind.VIEW, "graph_projection").value == (
        "graph_projection"
    )
    assert registry.resolve(NamespaceKind.FAMILY, "dynamic_logic").value == "program"
    assert registry.resolve(NamespaceKind.LANE, "runtime").value == "runtime_monitor"


def test_unknown_labels_fail_closed() -> None:
    with pytest.raises(UnknownAliasError):
        BASELINE_ALIAS_REGISTRY.resolve(NamespaceKind.FAMILY, "not_a_real_family")

    diagnostic = BASELINE_ALIAS_REGISTRY.diagnose(
        NamespaceKind.FAMILY, "not_a_real_family"
    )
    assert not diagnostic.ok
    assert diagnostic.disposition is MigrationDisposition.REJECTED_UNKNOWN
    assert diagnostic.error_code == "unknown_label"
    assert diagnostic.resolved is None


def test_wrong_namespace_labels_fail_closed() -> None:
    # smt is a notation, never a family.
    with pytest.raises(WrongNamespaceError):
        BASELINE_ALIAS_REGISTRY.resolve(NamespaceKind.FAMILY, "smt")

    diagnostic = BASELINE_ALIAS_REGISTRY.diagnose(NamespaceKind.FAMILY, "smt")
    assert diagnostic.disposition is MigrationDisposition.REJECTED_WRONG_NAMESPACE
    assert diagnostic.error_code == "wrong_namespace"
    assert "notation" in diagnostic.known_namespaces
    assert diagnostic.resolved is None

    # safety is a property, not a family.
    with pytest.raises(WrongNamespaceError):
        BASELINE_ALIAS_REGISTRY.resolve(NamespaceKind.FAMILY, "safety")

    # providers are not families.
    with pytest.raises(WrongNamespaceError):
        BASELINE_ALIAS_REGISTRY.resolve(NamespaceKind.FAMILY, "lean")
    with pytest.raises(WrongNamespaceError):
        BASELINE_ALIAS_REGISTRY.resolve(NamespaceKind.FAMILY, "proverif")

    # VC / verification_condition is a view, not a property or family.
    with pytest.raises(WrongNamespaceError):
        BASELINE_ALIAS_REGISTRY.resolve(NamespaceKind.FAMILY, "verification_condition")
    with pytest.raises(WrongNamespaceError):
        BASELINE_ALIAS_REGISTRY.resolve(NamespaceKind.PROPERTY, "VC")

    # hyperltl is a profile, not a family.
    with pytest.raises(WrongNamespaceError):
        BASELINE_ALIAS_REGISTRY.resolve(NamespaceKind.FAMILY, "hyperltl")

    # secpal is a profile, not a family.
    with pytest.raises(WrongNamespaceError):
        BASELINE_ALIAS_REGISTRY.resolve(NamespaceKind.FAMILY, "secpal")


def test_alias_collisions_impossible() -> None:
    catalog = _mutable_namespaces()
    registry = LogicAliasRegistry(namespaces=catalog)

    registry.register("legacy_fol", "first_order", namespace=NamespaceKind.FAMILY)

    with pytest.raises(AliasCollisionError):
        registry.register(
            "legacy_fol", "first_order", namespace=NamespaceKind.FAMILY
        )

    with pytest.raises(AliasCollisionError):
        registry.register(
            "LEGACY-FOL", "program", namespace=NamespaceKind.FAMILY
        )

    # Source that collides with an existing catalog alias for a different target.
    with pytest.raises(AliasCollisionError):
        registry.register("fol", "program", namespace=NamespaceKind.FAMILY)

    # Source that is already a catalog alias for the same target is still a
    # collision (single authority for the surface form).
    with pytest.raises(AliasCollisionError):
        registry.register("fol", "first_order", namespace=NamespaceKind.FAMILY)

    # Edge whose source normalizes to its target is rejected.
    with pytest.raises(AliasCollisionError):
        AliasEdge(source="first_order", target=family_id("first_order"))

    with pytest.raises(AliasCollisionError):
        AliasEdge(source="First-Order", target=family_id("first_order"))


def test_alias_cycles_impossible() -> None:
    """Cycles cannot be introduced: reverse edges collide; detector fails closed."""

    catalog = LogicIdentityNamespaces()
    catalog.register(NamespaceKind.FAMILY, "alpha")
    catalog.register(NamespaceKind.FAMILY, "beta")
    registry = LogicAliasRegistry(namespaces=catalog)
    registry.register("alias_alpha", "alpha", namespace=NamespaceKind.FAMILY)

    # Canonical identities cannot become alias sources (blocks reverse edges).
    with pytest.raises(AliasCollisionError):
        registry.register("alpha", "beta", namespace=NamespaceKind.FAMILY)
    with pytest.raises(AliasCollisionError):
        registry.register("beta", "alpha", namespace=NamespaceKind.FAMILY)

    # Self-edge at the AliasEdge layer (source normalizes to target).
    with pytest.raises(AliasCollisionError):
        AliasEdge(source="alpha", target=family_id("alpha"))

    # Cycle detector: planted map right -> left makes left -> right cyclic.
    catalog2 = LogicIdentityNamespaces()
    catalog2.register(NamespaceKind.FAMILY, "left")
    catalog2.register(NamespaceKind.FAMILY, "right")
    cyc_reg = LogicAliasRegistry(namespaces=catalog2)
    cyc_reg._edges[(NamespaceKind.FAMILY, "right")] = AliasEdge(
        source="right_alias",
        target=family_id("left"),
    )
    assert not cyc_reg._would_cycle(
        AliasEdge(source="from_left", target=family_id("right"))
    )
    cyclic = AliasEdge(source="left", target=family_id("right"))
    assert cyc_reg._would_cycle(cyclic)

    # Normal registration collides because "left" is a catalog identity.
    with pytest.raises(AliasCollisionError):
        cyc_reg.register_edge(cyclic)

    # When the catalog collision gate is not the first failure, the cycle
    # detector still fails closed with AliasCycleError.
    cyc_reg._namespaces.contains = lambda namespace, name: False  # type: ignore[method-assign]
    with pytest.raises(AliasCycleError):
        cyc_reg.register_edge(cyclic)

    assert issubclass(AliasCycleError, AliasError)


def test_canonicalization_is_deterministic_and_idempotent() -> None:
    registry = BASELINE_ALIAS_REGISTRY
    labels = (
        ("family", "fol"),
        ("family", "FOL"),
        ("family", "first_order"),
        ("family", "protocol"),
        ("notation", "smt"),
        ("notation", "SMT-LIB2"),
        ("profile", "tla+"),
        ("profile", "hyperltl"),
        ("view", "VC"),
        ("property", "safety"),
        ("provider", "coq"),
        ("lane", "runtime"),
    )
    for namespace, label in labels:
        first = registry.canonicalize(namespace, label)
        second = registry.canonicalize(namespace, label)
        assert first == second
        # Idempotent: canonicalizing the canonical value is a fixed point.
        third = registry.canonicalize(namespace, first.value)
        assert third == first
        fourth = registry.canonicalize(namespace, third.value)
        assert fourth == third

    # Same normalized input always yields the same identity object fields.
    a = registry.canonicalize(NamespaceKind.FAMILY, "predicate_logic")
    b = registry.canonicalize(NamespaceKind.FAMILY, "PREDICATE-LOGIC")
    assert a == b
    assert a.to_dict() == b.to_dict()


def test_one_write_emits_only_canonical_values() -> None:
    registry = BASELINE_ALIAS_REGISTRY

    written = registry.write_value(NamespaceKind.FAMILY, "fol")
    assert written == "first_order"
    assert written != "fol"

    written_protocol = registry.write_value(NamespaceKind.FAMILY, "protocol")
    assert written_protocol == "cryptographic_protocol"

    identity = registry.canonicalize(NamespaceKind.PROVIDER, "coq")
    emitted = registry.write(identity)
    assert emitted.value == "rocq"
    assert emitted == provider_id("rocq")

    # Module helpers.
    resolved, diagnostic = dual_read(NamespaceKind.FAMILY, "dynamic_logic")
    assert resolved.value == "program"
    assert diagnostic.was_alias
    assert one_write(resolved).value == "program"
    assert canonicalize_label(NamespaceKind.NOTATION, "smt").value == "smt_lib2"

    # Wrong-namespace write fails closed.
    with pytest.raises(WrongNamespaceError):
        registry.write(family_id("first_order"), namespace=NamespaceKind.PROVIDER)

    with pytest.raises(UnknownAliasError):
        registry.write(family_id("not_registered_family_zzzz"))


def test_canonical_read_is_not_marked_replaced() -> None:
    identity, diagnostic = BASELINE_ALIAS_REGISTRY.read(
        NamespaceKind.FAMILY, "first_order"
    )
    assert identity.value == "first_order"
    assert diagnostic.disposition is MigrationDisposition.CANONICAL
    assert not diagnostic.was_alias
    assert diagnostic.resolution_kind is AliasResolutionKind.CANONICAL


def test_migration_diagnostic_round_trip() -> None:
    _, diagnostic = BASELINE_ALIAS_REGISTRY.read(NamespaceKind.FAMILY, "fol")
    payload = diagnostic.to_dict()
    restored = LogicMigrationDiagnostic.from_dict(payload)
    assert restored == diagnostic
    assert json.loads(diagnostic.to_json()) == payload

    # Rejected diagnostic round-trip.
    rejected = BASELINE_ALIAS_REGISTRY.diagnose(NamespaceKind.FAMILY, "smt")
    restored_rejected = LogicMigrationDiagnostic.from_dict(rejected.to_dict())
    assert restored_rejected == rejected
    assert restored_rejected.known_namespaces == rejected.known_namespaces


def test_alias_registry_round_trip_and_freeze() -> None:
    catalog = _mutable_namespaces()
    registry = LogicAliasRegistry(namespaces=catalog)
    registry.register(
        "protocol",
        "cryptographic_protocol",
        namespace=NamespaceKind.FAMILY,
        notes="legacy protocol label",
    )
    registry.register(
        "policy",
        "secpal",
        namespace=NamespaceKind.PROFILE,
    )
    payload = registry.to_dict()
    assert payload["interface"] == ALIAS_INTERFACE
    assert payload["schema_version"] == ALIAS_SCHEMA_VERSION

    restored = LogicAliasRegistry.from_dict(
        payload, namespaces=catalog, frozen=True
    )
    assert restored.resolve(NamespaceKind.FAMILY, "protocol").value == (
        "cryptographic_protocol"
    )
    assert restored.resolve(NamespaceKind.PROFILE, "policy").value == "secpal"
    assert restored.frozen
    with pytest.raises(FrozenAliasRegistryError):
        restored.register("x", "first_order", namespace=NamespaceKind.FAMILY)

    # JSON parse path.
    again = LogicAliasRegistry.parse(
        registry.to_json(), namespaces=catalog, frozen=True
    )
    assert again.to_dict() == restored.to_dict()

    with pytest.raises(SchemaVersionError):
        LogicAliasRegistry.from_dict(
            {**payload, "schema_version": "nope/v0"}, namespaces=catalog
        )


def test_alias_edge_frozen_and_validated() -> None:
    edge = AliasEdge(
        source="protocol",
        target=family_id("cryptographic_protocol"),
        notes="legacy",
    )
    assert edge.namespace is NamespaceKind.FAMILY
    assert edge.replacement == "cryptographic_protocol"
    assert edge.source_key == "protocol"
    with pytest.raises(FrozenInstanceError):
        edge.source = "other"  # type: ignore[misc]

    with pytest.raises(InvalidIdentifierError):
        AliasEdge(source="", target=family_id("first_order"))

    with pytest.raises(InvalidIdentifierError):
        AliasEdge(
            source="x",
            target=family_id("first_order"),
            replacement="program",
        )

    # Wrong namespace declaration in payload.
    with pytest.raises(WrongNamespaceError):
        AliasEdge.from_dict(
            {
                "source": "x",
                "namespace": "provider",
                "target": family_id("first_order").to_dict(),
            }
        )


def test_build_baseline_is_frozen_and_idempotent() -> None:
    first = build_baseline_alias_registry(frozen=True)
    second = build_baseline_alias_registry(frozen=True)
    assert first.to_dict() == second.to_dict()
    assert first.frozen
    assert BASELINE_ALIAS_REGISTRY.to_dict() == first.to_dict()

    # Dual-read many is deterministic.
    many = first.canonicalize_many(
        NamespaceKind.FAMILY, ("fol", "protocol", "dynamic_logic", "first_order")
    )
    assert [item.value for item in many] == [
        "first_order",
        "cryptographic_protocol",
        "program",
        "first_order",
    ]


def test_contains_and_is_canonical() -> None:
    registry = BASELINE_ALIAS_REGISTRY
    assert registry.contains(NamespaceKind.FAMILY, "fol")
    assert registry.contains(NamespaceKind.FAMILY, "first_order")
    assert not registry.contains(NamespaceKind.FAMILY, "smt")
    assert not registry.contains(NamespaceKind.FAMILY, "nope")

    assert registry.is_canonical(NamespaceKind.FAMILY, "first_order")
    assert not registry.is_canonical(NamespaceKind.FAMILY, "fol")
    assert registry.is_canonical(NamespaceKind.NOTATION, "smt_lib2")
    assert not registry.is_canonical(NamespaceKind.NOTATION, "smt")


def test_diagnose_invalid_empty_label() -> None:
    diagnostic = BASELINE_ALIAS_REGISTRY.diagnose(NamespaceKind.FAMILY, "   ")
    assert not diagnostic.ok
    assert diagnostic.error_code == "invalid_label"


def test_state_transition_and_related_family_aliases() -> None:
    registry = BASELINE_ALIAS_REGISTRY
    assert registry.resolve(NamespaceKind.FAMILY, "state_transition").value == (
        "transition_system"
    )
    assert registry.resolve(NamespaceKind.FAMILY, "protocol_family").value == (
        "cryptographic_protocol"
    )
    assert registry.resolve(NamespaceKind.PROPERTY, "noninterference").value == (
        "noninterference"
    )
    assert registry.resolve(NamespaceKind.PROPERTY, "non_interference").value == (
        "noninterference"
    )


def test_edges_iteration_is_deterministic() -> None:
    registry = build_baseline_alias_registry(frozen=True)
    edges = registry.edges()
    assert list(edges) == sorted(
        edges, key=lambda item: (item.namespace.value, item.source_key, item.source)
    )
    assert len(registry) == len(edges)
    assert list(registry) == list(edges)

    family_edges = registry.edges(NamespaceKind.FAMILY)
    assert all(edge.namespace is NamespaceKind.FAMILY for edge in family_edges)
    assert "protocol" in {edge.source for edge in family_edges}


def test_unknown_target_rejected_at_registration() -> None:
    catalog = _mutable_namespaces()
    registry = LogicAliasRegistry(namespaces=catalog)
    with pytest.raises(UnknownAliasError):
        registry.register(
            "ghost",
            "not_in_catalog",
            namespace=NamespaceKind.FAMILY,
        )


def test_write_collapses_catalog_alias_identity_values() -> None:
    """If a LogicIdentity is built with an alias string as value, write rewrites."""

    # family_id validates identifiers — "fol" is a valid identifier form.
    alias_shaped = family_id("fol")
    # Dual-read resolves fol, then write emits canonical first_order.
    # require_identity may fail because fol is not a registered *canonical*
    # value — write uses resolve first.
    registry = BASELINE_ALIAS_REGISTRY
    # resolve works for "fol"
    assert registry.resolve(NamespaceKind.FAMILY, "fol").value == "first_order"
    # write on an identity whose value is the alias surface:
    # resolve(namespace, identity.value) → first_order, then require_identity.
    emitted = registry.write(alias_shaped)
    assert emitted.value == "first_order"
