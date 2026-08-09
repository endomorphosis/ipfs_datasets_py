"""Conformance: public API dual-read / canonical-write migration (LFP-044 / LFP-051).

Acceptance:

* Discovery exposes separate family/profile/property/view/notation/provider/
  encoding/evidence (and lane) namespaces
* Legacy aliases dual-read with typed diagnostics and are never written
* Existing accepted artifacts migrate deterministically to canonical labels
* New artifacts contain no legacy / free-form family labels
* Callers can inspect translation loss and provider authority without
  backend-specific heuristics

Interfaces: VerificationAPI@2, CanonicalLogicDiscovery@1
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ipfs_datasets_py.logic.api import (
    CANONICAL_LOGIC_DISCOVERY_INTERFACE as API_DISCOVERY_IFACE,
    CanonicalLogicDiscovery as ApiCanonicalLogicDiscovery,
    VERIFICATION_API_V2_INTERFACE as API_V2_IFACE,
    dual_read_label as api_dual_read_label,
    get_canonical_discovery as api_get_canonical_discovery,
    migrate_artifact as api_migrate_artifact,
)
from ipfs_datasets_py.logic.verification_api import (
    CANONICAL_LOGIC_DISCOVERY_INTERFACE,
    MIGRATION_OPERATIONS,
    VERIFICATION_API_V2_INTERFACE,
    CanonicalLogicDiscovery,
    LogicVerificationAPI,
    VerificationAuthority,
    VerificationStatus,
    canonical_write_label,
    dual_read_label,
    get_canonical_discovery,
    get_verification_api,
    inspect_provider_authority,
    inspect_translation_loss,
    list_logic_families,
    list_namespace_identities,
    list_namespaces,
    migrate_artifact,
)


# Plan evidence cases: fol/smt/tla_plus/hyperltl/protocol/secpal/VC/safety/provider/view
_PLAN_DUAL_READ_CASES: tuple[tuple[str, str, str], ...] = (
    ("family", "fol", "first_order"),
    ("notation", "smt", "smt_lib2"),
    ("notation", "smtlib2", "smt_lib2"),
    ("profile", "tla_plus", "tla_plus"),
    ("profile", "hyperltl", "hyperltl"),
    ("family", "protocol", "cryptographic_protocol"),
    ("profile", "secpal", "secpal"),
    ("view", "VC", "verification_condition"),
    ("property", "safety", "safety"),
    ("provider", "z3", "z3"),
    ("view", "graph_projection", "graph_projection"),
    ("lane", "runtime", "runtime_monitor"),
)

_REQUIRED_NAMESPACES = frozenset(
    {
        "family",
        "profile",
        "property",
        "view",
        "notation",
        "encoding",
        "provider",
        "lane",
        "evidence",
    }
)


def test_interface_identity_and_operations() -> None:
    assert CANONICAL_LOGIC_DISCOVERY_INTERFACE == "CanonicalLogicDiscovery@1"
    assert VERIFICATION_API_V2_INTERFACE == "VerificationAPI@2"
    discovery = CanonicalLogicDiscovery()
    assert discovery.interface == CANONICAL_LOGIC_DISCOVERY_INTERFACE
    payload = discovery.to_dict()
    assert payload["interface"] == "CanonicalLogicDiscovery@1"
    for operation in (
        "list_namespaces",
        "list_namespace_identities",
        "dual_read_label",
        "canonical_write_label",
        "migrate_artifact",
        "inspect_translation_loss",
        "inspect_provider_authority",
    ):
        assert operation in MIGRATION_OPERATIONS
        assert operation in payload["operations"]

    api = LogicVerificationAPI()
    api_payload = api.to_dict()
    assert api_payload["verification_api_v2"] == VERIFICATION_API_V2_INTERFACE
    assert api_payload["canonical_discovery_interface"] == (
        CANONICAL_LOGIC_DISCOVERY_INTERFACE
    )


# Legacy dual-read surface forms that must never be emitted as write values
# in the namespace where they are aliases.  The same token may be canonical in
# a different namespace (e.g. lane ``smt`` vs notation alias ``smt``).
_LEGACY_WRITE_FORBIDDEN: dict[str, frozenset[str]] = {
    "family": frozenset({"fol", "protocol"}),
    "notation": frozenset({"smt", "smtlib2"}),
    "view": frozenset({"VC", "vc"}),
    "lane": frozenset({"runtime"}),
    "profile": frozenset(),
    "property": frozenset(),
    "encoding": frozenset(),
    "provider": frozenset(),
    "evidence": frozenset(),
}


def test_discovery_exposes_separate_namespaces() -> None:
    response = list_namespaces()
    assert response.status is VerificationStatus.DECLARATIVE
    assert response.authority is VerificationAuthority.DECLARATIVE
    names = {item["namespace"] for item in response.result["namespaces"]}
    assert _REQUIRED_NAMESPACES <= names

    # Each namespace lists only canonical identities (never legacy aliases).
    for namespace in sorted(_REQUIRED_NAMESPACES):
        listed = list_namespace_identities(namespace)
        assert listed.status is VerificationStatus.DECLARATIVE
        values = [item["value"] for item in listed.result["identities"]]
        assert values == sorted(values)
        forbidden = _LEGACY_WRITE_FORBIDDEN.get(namespace, frozenset())
        for value in values:
            assert value == value.strip()
            assert value == value.casefold() or "_" in value or value.isalnum()
            # Legacy surface forms must not appear as registered write values
            # in the namespace where they are dual-read aliases.
            assert value not in forbidden


def test_list_logic_families_is_canonical_only() -> None:
    response = list_logic_families()
    assert response.status is VerificationStatus.DECLARATIVE
    family_ids = [item["family_id"] for item in response.result["families"]]
    assert family_ids
    assert "fol" not in family_ids
    assert "protocol" not in family_ids
    assert "first_order" in family_ids or any(
        item.get("namespace") == "family" for item in response.result["families"]
    )
    assert response.result["canonical_discovery"] == CANONICAL_LOGIC_DISCOVERY_INTERFACE
    assert response.result["verification_api"] == VERIFICATION_API_V2_INTERFACE
    assert "namespace_counts" in response.result
    for namespace in _REQUIRED_NAMESPACES:
        assert namespace in response.result["namespace_counts"]


@pytest.mark.parametrize(
    ("namespace", "observed", "canonical"),
    _PLAN_DUAL_READ_CASES,
)
def test_plan_evidence_dual_read(
    namespace: str, observed: str, canonical: str
) -> None:
    response = dual_read_label(namespace, observed)
    assert response.status is VerificationStatus.DECLARATIVE
    assert response.result["canonical"] == canonical
    assert response.result["identity"]["value"] == canonical
    assert response.result["identity"]["namespace"] == namespace
    diagnostic = response.result["diagnostic"]
    assert diagnostic["disposition"] in {"canonical", "replaced"}
    assert diagnostic["resolved"] is not None
    # Dual-read must never claim the legacy form is the write value when replaced.
    if observed != canonical:
        assert response.result["was_alias"] is True
        assert diagnostic["disposition"] == "replaced"
        assert diagnostic["replacement"] == canonical


def test_wrong_namespace_and_unknown_fail_closed() -> None:
    # smt is notation, not a family.
    wrong = dual_read_label("family", "smt")
    assert wrong.status in {
        VerificationStatus.INVALID,
        VerificationStatus.UNSUPPORTED,
    }
    assert wrong.result["identity"] is None
    assert wrong.result["diagnostic"]["disposition"] == "rejected_wrong_namespace"

    # safety is a property, not a family.
    safety = dual_read_label("family", "safety")
    assert safety.result["identity"] is None

    unknown = dual_read_label("family", "not_a_real_family_xyz")
    assert unknown.result["identity"] is None
    assert unknown.result["diagnostic"]["disposition"] == "rejected_unknown"

    write = canonical_write_label("family", "smt")
    assert write.status is VerificationStatus.INVALID
    assert write.result["identity"] is None


def test_canonical_write_never_emits_legacy_aliases() -> None:
    for namespace, observed, canonical in _PLAN_DUAL_READ_CASES:
        response = canonical_write_label(namespace, observed)
        assert response.status is VerificationStatus.SUCCEEDED
        assert response.result["canonical"] == canonical
        assert response.result["legacy_written"] is False
        assert response.result["identity"]["value"] == canonical
        # Idempotent: writing the canonical value is a fixed point.
        again = canonical_write_label(namespace, canonical)
        assert again.result["canonical"] == canonical


def test_migrate_artifact_is_deterministic_and_canonical() -> None:
    legacy_artifact: dict[str, Any] = {
        "family_id": "fol",
        "provider_id": "z3",
        "property_id": "safety",
        "view_role": "VC",
        "notation": "smt",
        "lane": "runtime",
        "profile": "hyperltl",
        "obligation": "check-auth",
    }
    first = migrate_artifact(legacy_artifact)
    second = migrate_artifact(legacy_artifact)
    assert first.status is VerificationStatus.SUCCEEDED
    assert second.status is VerificationStatus.SUCCEEDED
    left = first.result["artifact"]
    right = second.result["artifact"]
    # Strip volatile diagnostic list order is already deterministic via registry.
    assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
    assert left["family_id"] == "first_order"
    assert left["provider_id"] == "z3"
    assert left["property_id"] == "safety"
    assert left["view_role"] == "verification_condition"
    assert left["notation"] == "smt_lib2"
    assert left["lane"] == "runtime_monitor"
    assert left["profile"] == "hyperltl"
    assert left["canonical_only"] is True
    # Legacy surface forms must not remain on rewritten fields.
    for legacy in ("fol", "VC", "smt", "runtime", "protocol"):
        assert left.get("family_id") != legacy
        assert left.get("view_role") != legacy
        assert left.get("notation") != legacy
        assert left.get("lane") != legacy
    # Non-label fields are preserved.
    assert left["obligation"] == "check-auth"
    assert first.result["canonical_only"] is True


def test_migrate_artifact_rejects_free_form_family_labels() -> None:
    response = migrate_artifact({"family_id": "totally_free_form_family"})
    assert response.status is VerificationStatus.INVALID
    assert response.result["artifact"] is None


def test_inspect_translation_loss_without_backend_heuristics() -> None:
    structured = inspect_translation_loss(
        {
            "preservation_relation": "equisatisfiable",
            "authority_ceiling": "bounded",
            "unsupported_nodes": ["modal_box"],
            "approximated_nodes": [],
            "dropped_nodes": [],
            "assumptions": ("finite_domain",),
            "proof_safe": False,
            "counterexample_safe": True,
        }
    )
    assert structured.status is VerificationStatus.DECLARATIVE
    result = structured.result
    assert result["has_loss"] is True
    assert result["preservation_relation"] == "equisatisfiable"
    assert result["authority_ceiling"] == "bounded"
    assert result["unsupported_nodes"] == ["modal_box"]
    assert result["assumptions"] == ["finite_domain"]
    assert result["proof_safe"] is False
    assert result["counterexample_safe"] is True

    legacy_flag = inspect_translation_loss({"loss": True, "relation": "heuristic"})
    assert legacy_flag.result["has_loss"] is True
    assert legacy_flag.result["loss_kind"] == "boolean_legacy_flag"
    assert legacy_flag.result["preservation_relation"] == "heuristic"


def test_inspect_provider_authority_without_backend_heuristics() -> None:
    response = inspect_provider_authority("z3")
    assert response.status is VerificationStatus.DECLARATIVE
    assert response.provider_id == "z3"
    assert response.result["provider_id"] == "z3"
    assert "authority_ceiling" in response.result
    assert "availability" in response.result
    assert response.result["interface"] == CANONICAL_LOGIC_DISCOVERY_INTERFACE


def test_logic_api_lazy_exports_migration_surface() -> None:
    """``logic.api`` dual-reads the migration surface without changing exact_exports."""

    assert API_DISCOVERY_IFACE == CANONICAL_LOGIC_DISCOVERY_INTERFACE
    assert API_V2_IFACE == VERIFICATION_API_V2_INTERFACE
    assert isinstance(api_get_canonical_discovery(), ApiCanonicalLogicDiscovery)
    response = api_dual_read_label("family", "fol")
    assert response.result["canonical"] == "first_order"
    migrated = api_migrate_artifact({"family_id": "fol", "provider_id": "z3"})
    assert migrated.result["artifact"]["family_id"] == "first_order"


def test_module_wrappers_match_facade() -> None:
    api = get_verification_api(reset=True)
    discovery = get_canonical_discovery(reset=True)
    assert discovery.interface == CANONICAL_LOGIC_DISCOVERY_INTERFACE

    via_module = dual_read_label("family", "fol")
    via_facade = api.dual_read_label("family", "fol")
    assert via_module.result["canonical"] == via_facade.result["canonical"]
    assert via_module.to_dict()["result"]["canonical"] == "first_order"

    write_module = canonical_write_label("family", "fol")
    write_facade = api.canonical_write_label("family", "fol")
    assert write_module.result["canonical"] == write_facade.result["canonical"] == (
        "first_order"
    )


def test_discovery_serialization_is_deterministic() -> None:
    discovery = CanonicalLogicDiscovery()
    first = discovery.to_dict()
    second = discovery.to_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert set(first["identities"]) == _REQUIRED_NAMESPACES | set(first["identities"])
    for namespace, identities in first["identities"].items():
        values = [item["value"] for item in identities]
        assert values == sorted(values)
