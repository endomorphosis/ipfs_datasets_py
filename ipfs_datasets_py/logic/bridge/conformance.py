"""Family conformance receipts and compact recipe vectors for PGIR-020.

Recipes generate envelopes rather than checking in full golden dumps.  Each
receipt binds family identity, construct coverage, and the DomainLogicSlice
projection role.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_ROUNDTRIP_IR_INTERFACE,
    CANONICAL_TYPED_BRIDGE_CONFORMANCE_INTERFACE,
    CANONICAL_TYPED_BRIDGE_INTERFACE,
    REGISTERED_BRIDGE_FAMILY_IDS,
    BridgeAssumption,
    BridgeRepresentationKind,
    BridgeView,
    CanonicalRoundTripIR,
    CanonicalRule,
    CanonicalTypedBridge,
    ConstructDisposition,
    RequiredBridgeConstruct,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes, cid_for_dag_json

from .canonical import (
    FORMALIZATION_ARTIFACT_SCHEMA_ID,
    LEGAL_IR_DOCUMENT_SCHEMA_ID,
    compose_typed_bridge,
    extract_canonical_ir,
    wrap_canonical_ir,
    wrap_formalization_artifact,
    wrap_legal_ir_document,
)
from .constructs import (
    construct_coverage,
    is_forbidden_family_id,
    unexplained_constructs,
)
from .registry import logic_bridge_specs
from .types import LegalIRDocument, LogicIRView


FAMILY_CONFORMANCE_SCHEMA_VERSION: Final = (
    "ipfs-datasets.canonical-typed-bridge-conformance.v1"
)


@dataclass(frozen=True, slots=True)
class FamilyConformanceVector:
    """One compact family recipe used to generate a conformance envelope."""

    vector_id: str
    family_id: str
    authority_schema: str
    builder: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_schema": self.authority_schema,
            "builder": self.builder,
            "family_id": self.family_id,
            "vector_id": self.vector_id,
        }


@dataclass(frozen=True, slots=True)
class FamilyConformanceReceipt:
    """Deterministic receipt that one family round-trip retained identity."""

    vector_id: str
    family_id: str
    bridge_cid: str
    payload_cid: str
    slice_disposition: str
    construct_dispositions: Mapping[str, str]
    family_round_trip: bool
    slice_is_not_family: bool
    unexplained: tuple[str, ...]

    def identity_payload(self) -> dict[str, Any]:
        return {
            "bridge_cid": self.bridge_cid,
            "construct_dispositions": dict(self.construct_dispositions),
            "family_id": self.family_id,
            "family_round_trip": self.family_round_trip,
            "interface": CANONICAL_TYPED_BRIDGE_CONFORMANCE_INTERFACE,
            "payload_cid": self.payload_cid,
            "schema_version": FAMILY_CONFORMANCE_SCHEMA_VERSION,
            "slice_disposition": self.slice_disposition,
            "slice_is_not_family": self.slice_is_not_family,
            "unexplained": list(self.unexplained),
            "vector_id": self.vector_id,
        }

    @property
    def receipt_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "receipt_cid": self.receipt_cid}


def _canonical_rule() -> CanonicalRule:
    return CanonicalRule(
        modality="O",
        actor="agency",
        action="publish",
        object="notice",
        conditions=("request_received",),
        exceptions=("emergency",),
        temporal=(),
    )


def _canonical_bridge() -> CanonicalTypedBridge:
    return wrap_canonical_ir(
        CanonicalRoundTripIR((_canonical_rule(),)),
        family_id="canonical_roundtrip",
        source_text="Agency shall publish notice unless an emergency applies.",
    )


def _legal_document_bridge() -> CanonicalTypedBridge:
    text = "Agency shall publish notice."
    document = LegalIRDocument(
        document_id="legal:notice",
        source_text=text,
        normalized_text=text,
        source="us_code",
        citation="Fixture § 1",
        views={
            "deontic_ir": LogicIRView(
                name="deontic_ir",
                payload={"modality": "O", "actor": "agency", "action": "publish"},
                format="deontic",
                source_component="deontic.ir",
            )
        },
        frame_logic_triples=({"subject": "agency", "predicate": "publish", "object": "notice"},),
        metadata={"fixture": "pgir-020"},
    )
    return wrap_legal_ir_document(document, family_id="legal", adapter_name="deontic_norms")


def _formalization_bridge(domain: str) -> CanonicalTypedBridge:
    artifact = {
        "assumptions": (
            {
                "assumption_id": f"{domain}:isolated",
                "statement": "The runtime isolates the declared actor.",
                "source_ref_ids": (f"source:{domain}",),
            },
        ),
        "declaration_digest": "sha256:" + ("ab" * 32),
        "declaration_id": f"{domain}:declaration",
        "digest": "sha256:" + ("cd" * 32),
        "domain": domain,
        "formulas": (
            {
                "formula_id": f"{domain}:formula",
                "view_id": f"{domain}.primary",
            },
        ),
        "sample_id": f"{domain}:sample",
        "schema_version": FORMALIZATION_ARTIFACT_SCHEMA_ID,
        "source_map": {
            "sources": (
                {
                    "content_cid": cid_for_bytes(b"reviewed family fixture"),
                    "ref_id": f"source:{domain}",
                    "source_revision": "revision-1",
                    "source_uri": f"repo://fixtures/{domain}.md",
                },
            )
        },
    }
    return wrap_formalization_artifact(artifact, family_id=domain)


_FAMILY_EXTENSION_RECIPES: Final[Mapping[str, Mapping[str, str]]] = {
    "tdfol": {
        "adapter_name": "fol_tdfol",
        "formula": "HoldsAt(publish(agency, notice), t)",
        "sort": "temporal",
        "view_name": "tdfol_formula",
    },
    "deontic": {
        "adapter_name": "deontic_norms",
        "formula": "O(publish(agency, notice))",
        "sort": "obligation",
        "view_name": "deontic_formula",
    },
    "modal": {
        "adapter_name": "modal_frame_logic",
        "formula": "Box(publish(agency, notice))",
        "sort": "alethic",
        "view_name": "modal_formula",
    },
    "cec": {
        "adapter_name": "cec_dcec",
        "formula": "Happens(publish(agency, notice), t)",
        "sort": "event",
        "view_name": "cec_formula",
    },
}


def _family_extension_bridge(family_id: str) -> CanonicalTypedBridge:
    recipe = _FAMILY_EXTENSION_RECIPES[family_id]
    schema_id = f"family.{family_id}"
    return compose_typed_bridge(
        family_id=family_id,
        authority_schema=schema_id,
        views=(
            BridgeView(
                name="logic_family",
                kind=BridgeRepresentationKind.LOGIC_FAMILY,
                schema_id=schema_id,
                family_id=family_id,
                payload={"family": family_id, "sort": recipe["sort"]},
            ),
            BridgeView(
                name=recipe["view_name"],
                kind=BridgeRepresentationKind.FAMILY_EXTENSION,
                schema_id=schema_id,
                family_id=family_id,
                payload={"formula": recipe["formula"]},
            ),
        ),
        assumptions=(
            BridgeAssumption(
                assumption_id=f"{family_id}:closed-world",
                statement=f"{family_id} evaluation is closed under the declared signature.",
            ),
        ),
        adapter_name=recipe["adapter_name"],
        metadata={"wrapped": schema_id},
    )


def family_conformance_vectors() -> tuple[FamilyConformanceVector, ...]:
    """Return the compact recipe set used by unit and family-conformance tests."""

    return (
        FamilyConformanceVector(
            vector_id="canonical-roundtrip",
            family_id="canonical_roundtrip",
            authority_schema=CANONICAL_ROUNDTRIP_IR_INTERFACE,
            builder="canonical_ir",
        ),
        FamilyConformanceVector(
            vector_id="legal-document",
            family_id="legal",
            authority_schema=LEGAL_IR_DOCUMENT_SCHEMA_ID,
            builder="legal_ir_document",
        ),
        FamilyConformanceVector(
            vector_id="legal-formalization",
            family_id="legal",
            authority_schema=FORMALIZATION_ARTIFACT_SCHEMA_ID,
            builder="formalization",
        ),
        FamilyConformanceVector(
            vector_id="security-formalization",
            family_id="security",
            authority_schema=FORMALIZATION_ARTIFACT_SCHEMA_ID,
            builder="formalization",
        ),
        FamilyConformanceVector(
            vector_id="intent-formalization",
            family_id="intent",
            authority_schema=FORMALIZATION_ARTIFACT_SCHEMA_ID,
            builder="formalization",
        ),
        FamilyConformanceVector(
            vector_id="tdfol-family",
            family_id="tdfol",
            authority_schema="family.tdfol",
            builder="family_extension",
        ),
        FamilyConformanceVector(
            vector_id="deontic-family",
            family_id="deontic",
            authority_schema="family.deontic",
            builder="family_extension",
        ),
        FamilyConformanceVector(
            vector_id="modal-family",
            family_id="modal",
            authority_schema="family.modal",
            builder="family_extension",
        ),
        FamilyConformanceVector(
            vector_id="cec-family",
            family_id="cec",
            authority_schema="family.cec",
            builder="family_extension",
        ),
    )


def build_conformance_bridge(vector: FamilyConformanceVector) -> CanonicalTypedBridge:
    """Materialize one recipe into a typed-bridge envelope."""

    if vector.builder == "canonical_ir":
        return _canonical_bridge()
    if vector.builder == "legal_ir_document":
        return _legal_document_bridge()
    if vector.builder == "formalization":
        return _formalization_bridge(vector.family_id)
    if vector.builder == "family_extension":
        return _family_extension_bridge(vector.family_id)
    raise ValueError(f"unknown conformance builder: {vector.builder!r}")


def evaluate_family_conformance(
    vector: FamilyConformanceVector,
    bridge: CanonicalTypedBridge | None = None,
) -> FamilyConformanceReceipt:
    """Evaluate one family recipe and return a content-addressed receipt."""

    envelope = build_conformance_bridge(vector) if bridge is None else bridge
    restored = CanonicalTypedBridge.from_dict(envelope.to_dict())
    family_round_trip = (
        restored.family_identity.family_id == vector.family_id
        and restored.bridge_cid == envelope.bridge_cid
        and not is_forbidden_family_id(restored.family_identity.family_id)
    )
    if vector.builder == "canonical_ir":
        family_round_trip = family_round_trip and (
            extract_canonical_ir(restored).ir_cid
            == extract_canonical_ir(envelope).ir_cid
        )
    slice_role = restored.domain_logic_slice
    slice_is_not_family = (
        slice_role is not None
        and slice_role.family_id == vector.family_id
        and slice_role.disposition is not ConstructDisposition.REPRESENTED
        and "domain_logic_slice" not in restored.views
    )
    return FamilyConformanceReceipt(
        vector_id=vector.vector_id,
        family_id=restored.family_identity.family_id,
        bridge_cid=restored.bridge_cid,
        payload_cid=restored.family_identity.payload_cid,
        slice_disposition=slice_role.disposition.value if slice_role else "absent",
        construct_dispositions=construct_coverage(restored),
        family_round_trip=family_round_trip,
        slice_is_not_family=slice_is_not_family,
        unexplained=unexplained_constructs(restored),
    )


def family_conformance_receipts() -> tuple[FamilyConformanceReceipt, ...]:
    """Evaluate every compact family recipe."""

    return tuple(
        evaluate_family_conformance(vector) for vector in family_conformance_vectors()
    )


def adapter_conformance_records() -> tuple[dict[str, Any], ...]:
    """Describe existing registry adapters against the typed-bridge contract."""

    records: list[dict[str, Any]] = []
    for spec in logic_bridge_specs():
        family_id = spec.ast_scope or spec.name
        records.append(
            {
                "adapter_class": spec.adapter_class,
                "adapter_name": spec.name,
                "family_id": family_id,
                "family_registered": family_id in REGISTERED_BRIDGE_FAMILY_IDS,
                "implemented": spec.implemented,
                "roles": list(spec.roles),
                "source_view": spec.source_view,
                "target_component": spec.target_component,
                "target_views": list(spec.target_views),
                "typed_bridge_interface": CANONICAL_TYPED_BRIDGE_INTERFACE,
            }
        )
    return tuple(records)


def schema_golden_vectors() -> tuple[dict[str, Any], ...]:
    """Return compact schema vectors generated from the family recipes."""

    vectors: list[dict[str, Any]] = []
    for vector in family_conformance_vectors():
        bridge = build_conformance_bridge(vector)
        payload = bridge.to_dict()
        vectors.append(
            {
                "bridge_cid": bridge.bridge_cid,
                "constructs": [
                    construct.value for construct in RequiredBridgeConstruct
                ],
                "family_id": vector.family_id,
                "interface": payload["interface"],
                "schema_version": payload["schema_version"],
                "slice_kind": (
                    bridge.domain_logic_slice.projection_payload()["slice_kind"]
                    if bridge.domain_logic_slice.disposition
                    is ConstructDisposition.EXPLICIT_PARTIAL
                    else None
                ),
                "vector_id": vector.vector_id,
                "view_names": sorted(bridge.views),
            }
        )
    return tuple(vectors)


__all__ = [
    "FAMILY_CONFORMANCE_SCHEMA_VERSION",
    "FamilyConformanceReceipt",
    "FamilyConformanceVector",
    "adapter_conformance_records",
    "build_conformance_bridge",
    "evaluate_family_conformance",
    "family_conformance_receipts",
    "family_conformance_vectors",
    "schema_golden_vectors",
]
