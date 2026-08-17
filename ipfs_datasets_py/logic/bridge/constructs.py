"""Closed catalog of required typed-bridge constructs.

Every required construct is either represented in a
:class:`~ipfs_datasets_py.logic.legal_ir.canonical_contracts.CanonicalTypedBridge`
or recorded as explicitly unsupported.  DomainLogicSlice is a projection role,
never a registered logic family.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_TYPED_BRIDGE_INTERFACE,
    CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION,
    CORE_BRIDGE_VIEW_NAMES,
    FORBIDDEN_BRIDGE_FAMILY_IDS,
    REGISTERED_BRIDGE_FAMILY_IDS,
    BridgeRepresentationKind,
    CanonicalTypedBridge,
    ConstructDisposition,
    RequiredBridgeConstruct,
)


CONSTRUCT_CATALOG_INTERFACE: Final = "CanonicalTypedBridgeConstructCatalog@1"
CONSTRUCT_CATALOG_VERSION: Final = "ipfs-datasets.canonical-typed-bridge-constructs.v1"

_CONSTRUCT_AUTHORITY_SCHEMAS: Final[Mapping[str, str]] = MappingProxyType(
    {
        RequiredBridgeConstruct.FAMILY_IDENTITY.value: "bridge.family_identity",
        RequiredBridgeConstruct.SOURCE_REFERENCES.value: "bridge.source_references",
        RequiredBridgeConstruct.ASSUMPTIONS.value: "bridge.assumptions",
        RequiredBridgeConstruct.PROVENANCE.value: "bridge.provenance",
        RequiredBridgeConstruct.UNSUPPORTED_CONSTRUCTS.value: (
            "bridge.unsupported_constructs"
        ),
        RequiredBridgeConstruct.SOURCE_TEXT.value: "source.legal_policy_text",
        RequiredBridgeConstruct.TYPED_SYNTAX.value: "typed.syntax",
        RequiredBridgeConstruct.CANONICAL_IR.value: "bridge.canonical_roundtrip_ir",
        RequiredBridgeConstruct.DOMAIN_LOGIC_SLICE.value: "bridge.domain_logic_slice",
        RequiredBridgeConstruct.LOGIC_FAMILY_REPRESENTATIONS.value: (
            "family.existing_logic"
        ),
        RequiredBridgeConstruct.FAMILY_EXTENSIONS.value: "bridge.family_extensions",
        RequiredBridgeConstruct.FORMALIZATION_ARTIFACT.value: (
            "typed.formalization_artifact"
        ),
        RequiredBridgeConstruct.LEGAL_IR_DOCUMENT.value: "bridge.legal_ir_document",
        RequiredBridgeConstruct.PROVER_SYNTAX.value: "prover.syntax",
        RequiredBridgeConstruct.CONTROLLED_NATURAL_LANGUAGE.value: (
            "cnl.controlled_text"
        ),
        RequiredBridgeConstruct.PROOF_TRACES.value: "trace.proof",
        RequiredBridgeConstruct.TACTIC_TRACES.value: "trace.tactic",
        RequiredBridgeConstruct.COUNTEREXAMPLE_TRACES.value: "trace.counterexample",
        RequiredBridgeConstruct.TRANSLATION_TRACES.value: "trace.translation",
    }
)


def required_bridge_constructs() -> tuple[str, ...]:
    """Return the closed required-construct catalog in stable order."""

    return tuple(item.value for item in RequiredBridgeConstruct)


def construct_authority_schema(construct_id: str) -> str:
    """Return the representation identifier owned by one required construct."""

    try:
        return _CONSTRUCT_AUTHORITY_SCHEMAS[construct_id]
    except KeyError as exc:
        raise KeyError(f"unknown required construct: {construct_id!r}") from exc


def is_registered_family_id(family_id: str) -> bool:
    """Return whether ``family_id`` is an existing family, not DomainLogicSlice."""

    return (
        family_id in REGISTERED_BRIDGE_FAMILY_IDS
        and family_id not in FORBIDDEN_BRIDGE_FAMILY_IDS
    )


def is_forbidden_family_id(family_id: str) -> bool:
    """Return whether ``family_id`` would invent or alias DomainLogicSlice."""

    return family_id in FORBIDDEN_BRIDGE_FAMILY_IDS or family_id.lower() in {
        item.lower() for item in FORBIDDEN_BRIDGE_FAMILY_IDS
    }


def construct_catalog() -> dict[str, Any]:
    """Return the immutable construct catalog used by schema golden vectors."""

    return {
        "core_view_names": sorted(CORE_BRIDGE_VIEW_NAMES),
        "forbidden_family_ids": sorted(FORBIDDEN_BRIDGE_FAMILY_IDS),
        "interface": CONSTRUCT_CATALOG_INTERFACE,
        "registered_family_ids": sorted(REGISTERED_BRIDGE_FAMILY_IDS),
        "representation_kinds": [item.value for item in BridgeRepresentationKind],
        "required_constructs": [
            {
                "authority_schema": construct_authority_schema(item.value),
                "construct_id": item.value,
            }
            for item in RequiredBridgeConstruct
        ],
        "schema_version": CONSTRUCT_CATALOG_VERSION,
        "typed_bridge_interface": CANONICAL_TYPED_BRIDGE_INTERFACE,
        "typed_bridge_schema_version": CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION,
    }


def construct_coverage(bridge: CanonicalTypedBridge) -> dict[str, str]:
    """Return the disposition of every required construct on one envelope."""

    return {key: value.value for key, value in bridge.construct_dispositions.items()}


def unexplained_constructs(bridge: CanonicalTypedBridge) -> tuple[str, ...]:
    """Return required constructs that are neither represented nor unsupported."""

    missing: list[str] = []
    for construct in RequiredBridgeConstruct:
        disposition = bridge.construct_dispositions.get(construct.value)
        if disposition not in {
            ConstructDisposition.REPRESENTED,
            ConstructDisposition.EXPLICIT_PARTIAL,
            ConstructDisposition.UNSUPPORTED,
        }:
            missing.append(construct.value)
    return tuple(missing)


__all__ = [
    "CONSTRUCT_CATALOG_INTERFACE",
    "CONSTRUCT_CATALOG_VERSION",
    "construct_authority_schema",
    "construct_catalog",
    "construct_coverage",
    "is_forbidden_family_id",
    "is_registered_family_id",
    "required_bridge_constructs",
    "unexplained_constructs",
]
