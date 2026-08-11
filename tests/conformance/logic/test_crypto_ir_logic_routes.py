"""Conformance: crypto_ir cryptocurrency-network typed logic routes (LFP-035).

Acceptance:

* Cryptocurrency-network semantics name attacker, consensus, finality, bound,
  arithmetic, and trace assumptions
* Legacy smt_lib/fol labels canonicalize or fail
* No future probabilistic/ZK claim is implied

Interfaces: CryptoNetworkFormalizationAdapter@1
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.crypto_ir.formalization.obligations import LogicFamily
from ipfs_datasets_py.logic.crypto_ir.formalization.typed_adapter import (
    CRYPTO_NETWORK_FORMALIZATION_ADAPTER_INTERFACE,
    FUTURE_UNSUPPORTED_FAMILY_CLAIMS,
    REQUIRED_ASSUMPTION_KINDS,
    CryptoNetworkAdapterError,
    CryptoNetworkFormalizationAdapter,
    CryptoNetworkViewKind,
    FutureClaimRejectedError,
    LabelDisposition,
    NetworkAssumptionKind,
    RouteSupport,
    UnknownLogicFamilyLabelError,
    adapt_crypto_network_view,
    canonicalize_crypto_logic_family,
    canonicalize_legacy_logic_family,
    default_crypto_network_profiles,
    default_crypto_network_routes,
    default_crypto_network_view_registry,
    diagnose_legacy_logic_family,
)
from ipfs_datasets_py.logic.families.profiles import (
    AttackerModel,
    PROFILE_INTERFACE,
    SemanticProfile,
)
from ipfs_datasets_py.logic.formalization.views import ViewRegistry


# ---------------------------------------------------------------------------
# Interface identity
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    assert (
        CryptoNetworkFormalizationAdapter.INTERFACE
        == CRYPTO_NETWORK_FORMALIZATION_ADAPTER_INTERFACE
    )
    assert adapter.interface == "CryptoNetworkFormalizationAdapter@1"
    assert adapter.domain_id == "crypto_ir"
    wire = adapter.to_dict()
    assert wire["interface"] == CRYPTO_NETWORK_FORMALIZATION_ADAPTER_INTERFACE
    assert wire["implies_future_claims"] is False
    assert wire["required_assumption_kinds"] == list(REQUIRED_ASSUMPTION_KINDS)


# ---------------------------------------------------------------------------
# Typed routes for every cryptocurrency-network view
# ---------------------------------------------------------------------------


EXPECTED_VIEWS = (
    "transactions",
    "balances",
    "consensus",
    "reorg_finality",
    "bridges",
    "wallets",
    "permissions",
    "symbolic_protocols",
    "arithmetic",
    "privacy",
)


def test_all_network_views_have_typed_routes() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    known = set(adapter.known_views())
    assert known == set(EXPECTED_VIEWS)
    for view in CryptoNetworkViewKind:
        route = adapter.route_for(view)
        assert route.view_kind is view
        assert route.family_id
        assert route.profile_id
        assert route.view_id.startswith("crypto-ir-view/")
        assert route.implies_future_claims is False
        assert isinstance(route.support, RouteSupport)


def test_adapt_crypto_network_view_helper() -> None:
    route = adapt_crypto_network_view("arithmetic")
    assert route.view_kind is CryptoNetworkViewKind.ARITHMETIC
    assert route.family_id == "first_order"
    assert route.notation_id == "smt_lib2"


def test_matrix_aligned_view_ids() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    # Plan / capability matrix crypto_ir cells that this adapter owns.
    assert adapter.route_for("reorg_finality").view_id == "crypto-ir-view/transition/v1"
    assert adapter.route_for("symbolic_protocols").view_id == "crypto-ir-view/protocol/v1"
    assert adapter.route_for("privacy").view_id == "crypto-ir-view/hyperproperty/v1"
    assert adapter.route_for("permissions").view_id == "crypto-ir-view/authorization/v1"
    assert adapter.route_for("arithmetic").view_id == "crypto-ir-view/smt/v1"


def test_unknown_view_fails_closed() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    with pytest.raises(CryptoNetworkAdapterError) as excinfo:
        adapter.route_for("not_a_crypto_view")
    assert excinfo.value.code == "crypto_network.unknown_view"


# ---------------------------------------------------------------------------
# Named assumptions: attacker, consensus, finality, bound, arithmetic, trace
# ---------------------------------------------------------------------------


def test_every_route_names_required_assumptions() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    required = set(REQUIRED_ASSUMPTION_KINDS)
    for route in adapter.routes:
        kinds = {item.kind.value for item in route.assumptions}
        assert kinds == required, f"{route.view_id} missing {required - kinds}"
        for kind in NetworkAssumptionKind:
            assumption = route.assumption(kind)
            assert assumption.statement
            assert assumption.profile_field
            assert assumption.value
            assert assumption.assumption_id.startswith("asm.crypto_network.")


def test_assumption_semantics_are_view_specific() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    bridges = adapter.route_for(CryptoNetworkViewKind.BRIDGES)
    assert bridges.assumption(NetworkAssumptionKind.ATTACKER).value == "dolev_yao"
    assert (
        bridges.assumption(NetworkAssumptionKind.FINALITY).value
        == "source_finality_before_mint"
    )
    reorg = adapter.route_for(CryptoNetworkViewKind.REORG_FINALITY)
    assert reorg.assumption(NetworkAssumptionKind.BOUND).value == "max_reorg_depth"
    assert reorg.assumption(NetworkAssumptionKind.FINALITY).value == "depth_or_checkpoint"
    arithmetic = adapter.route_for(CryptoNetworkViewKind.ARITHMETIC)
    assert arithmetic.assumption(NetworkAssumptionKind.ARITHMETIC).value == "linear_integer"
    privacy = adapter.route_for(CryptoNetworkViewKind.PRIVACY)
    assert privacy.assumption(NetworkAssumptionKind.TRACE).value == "finite"
    attacker_stmt = privacy.assumption(NetworkAssumptionKind.ATTACKER).statement.lower()
    assert "zk" in attacker_stmt and "not" in attacker_stmt


# ---------------------------------------------------------------------------
# Semantic profiles
# ---------------------------------------------------------------------------


def test_profiles_are_semantic_profile_v1() -> None:
    profiles = default_crypto_network_profiles()
    adapter = CryptoNetworkFormalizationAdapter()
    for route in adapter.routes:
        profile = adapter.profile_for(route.view_kind)
        assert isinstance(profile, SemanticProfile)
        assert profile.interface == PROFILE_INTERFACE
        assert profile.profile_id == route.profile_id
        assert profile.profile_id in profiles
        assert route.family_id in profile.family_ids


def test_protocol_routes_use_dolev_yao_attacker() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    for view in (
        CryptoNetworkViewKind.BRIDGES,
        CryptoNetworkViewKind.SYMBOLIC_PROTOCOLS,
    ):
        profile = adapter.profile_for(view)
        assert profile.attacker.model is AttackerModel.DOLEV_YAO


def test_view_registry_covers_all_routes() -> None:
    registry = default_crypto_network_view_registry()
    assert isinstance(registry, ViewRegistry)
    adapter = CryptoNetworkFormalizationAdapter()
    for route in adapter.routes:
        view = registry.resolve(route.view_id)
        assert view.logic_family == route.family_id
        assert view.metadata.to_dict().get("implies_future_claims") is False


# ---------------------------------------------------------------------------
# Legacy smt_lib / fol labels canonicalize or fail
# ---------------------------------------------------------------------------


def test_smt_lib_and_fol_canonicalize() -> None:
    family_smt, diag_smt = canonicalize_legacy_logic_family("smt_lib")
    assert family_smt == "first_order"
    assert diag_smt.ok is True
    assert diag_smt.disposition is LabelDisposition.ALIAS
    assert diag_smt.notation_id == "smt_lib2"
    assert diag_smt.profile_id == "smt_lib"

    family_fol, diag_fol = canonicalize_legacy_logic_family("fol")
    assert family_fol == "first_order"
    assert diag_fol.ok is True

    # Enum surface retained as diagnosed input alias only.
    family_enum, diag_enum = canonicalize_legacy_logic_family(LogicFamily.SMT_LIB)
    assert family_enum == "first_order"
    assert diag_enum.input_label == "smt_lib"

    family_fol_enum, _ = canonicalize_legacy_logic_family(LogicFamily.FOL)
    assert family_fol_enum == "first_order"


def test_smt_aliases_canonicalize() -> None:
    for label in ("smt", "smtlib2", LogicFamily.SMT_LIB):
        family, diagnostic = canonicalize_crypto_logic_family(label)
        assert family == "first_order"
        assert diagnostic.ok is True


def test_canonical_first_order_is_idempotent() -> None:
    family, diagnostic = canonicalize_legacy_logic_family("first_order")
    assert family == "first_order"
    assert diagnostic.disposition is LabelDisposition.CANONICAL


def test_unknown_logic_family_label_fails() -> None:
    with pytest.raises(UnknownLogicFamilyLabelError):
        canonicalize_legacy_logic_family("not_a_real_logic_family_xyz")
    diagnostic = diagnose_legacy_logic_family("not_a_real_logic_family_xyz")
    assert diagnostic.ok is False
    assert diagnostic.disposition is LabelDisposition.REJECTED_UNKNOWN


def test_opaque_and_prose_do_not_canonicalize_to_route_family() -> None:
    for label in (LogicFamily.OPAQUE, LogicFamily.PROSE, "opaque", "prose"):
        with pytest.raises(UnknownLogicFamilyLabelError):
            canonicalize_legacy_logic_family(label)


def test_route_for_legacy_smt_lib_selects_arithmetic() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    route, diagnostic = adapter.route_for_legacy_logic_family("smt_lib")
    assert diagnostic.ok is True
    assert route.view_kind is CryptoNetworkViewKind.ARITHMETIC
    assert route.family_id == "first_order"
    assert route.notation_id == "smt_lib2"


def test_route_for_legacy_fol_selects_compatible_first_order() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    route, diagnostic = adapter.route_for_legacy_logic_family(LogicFamily.FOL)
    assert diagnostic.ok is True
    assert route.family_id == "first_order"


def test_preferred_view_mismatch_fails() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    with pytest.raises(CryptoNetworkAdapterError):
        adapter.route_for_legacy_logic_family(
            "smt_lib",
            preferred_view=CryptoNetworkViewKind.PERMISSIONS,
        )


# ---------------------------------------------------------------------------
# No future probabilistic / ZK claim is implied
# ---------------------------------------------------------------------------


def test_no_future_claims_on_default_catalog() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    adapter.assert_no_future_claims()
    for route in adapter.routes:
        assert route.implies_future_claims is False
        assert route.family_id not in FUTURE_UNSUPPORTED_FAMILY_CLAIMS
        assert route.metadata.get("zk_claim") is not True
        assert route.metadata.get("probabilistic_claim") is not True
        assert route.metadata.get("finite_field_claim") is not True


def test_future_labels_are_rejected() -> None:
    for label in (
        "probabilistic",
        "finite_field_constraint",
        "zk",
        "zkp",
        "zero_knowledge",
        "fuzzy_weighted",
    ):
        with pytest.raises(FutureClaimRejectedError):
            canonicalize_legacy_logic_family(label)
        diagnostic = diagnose_legacy_logic_family(label)
        assert diagnostic.ok is False
        assert diagnostic.disposition is LabelDisposition.REJECTED_FUTURE


def test_privacy_route_explicitly_denies_zk() -> None:
    route = adapt_crypto_network_view(CryptoNetworkViewKind.PRIVACY)
    assert route.family_id == "hyperproperty"
    assert route.metadata.get("zk_claim") is False
    assert route.metadata.get("probabilistic_claim") is False
    attacker = route.assumption(NetworkAssumptionKind.ATTACKER)
    assert "zk" not in attacker.value.casefold()
    assert "not" in attacker.statement.casefold()


def test_default_routes_factory_is_stable() -> None:
    a = default_crypto_network_routes()
    b = default_crypto_network_routes()
    assert [route.view_id for route in a] == [route.view_id for route in b]
    assert len(a) == len(EXPECTED_VIEWS)


def test_adapter_serialization_round_trip_fields() -> None:
    adapter = CryptoNetworkFormalizationAdapter()
    payload = adapter.to_dict()
    assert len(payload["routes"]) == len(EXPECTED_VIEWS)
    for route_payload in payload["routes"]:
        kinds = {item["kind"] for item in route_payload["assumptions"]}
        assert kinds == set(REQUIRED_ASSUMPTION_KINDS)
        assert route_payload["implies_future_claims"] is False
