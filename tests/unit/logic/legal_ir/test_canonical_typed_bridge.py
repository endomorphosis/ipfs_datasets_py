"""Unit tests for the consolidated CanonicalTypedBridge@1 contract."""

from __future__ import annotations

import copy

import pytest

from ipfs_datasets_py.logic.bridge.canonical import (
    extract_canonical_ir,
    extract_formalization_artifact,
    extract_legal_ir_document,
    wrap_canonical_ir,
    wrap_compiler_result,
    wrap_formalization_artifact,
    wrap_legal_ir_document,
)
from ipfs_datasets_py.logic.bridge.conformance import (
    adapter_conformance_records,
    build_conformance_bridge,
    evaluate_family_conformance,
    family_conformance_receipts,
    family_conformance_vectors,
    schema_golden_vectors,
)
from ipfs_datasets_py.logic.bridge.constructs import (
    construct_catalog,
    construct_coverage,
    is_forbidden_family_id,
    required_bridge_constructs,
    unexplained_constructs,
)
from ipfs_datasets_py.logic.bridge.migrations import (
    BridgeMigrationSource,
    export_canonical_ir,
    export_formalization_artifact,
    export_legal_ir_document,
    migrate_canonical_ir,
    migrate_formalization_artifact,
    migrate_from_source,
    migrate_identity,
    migrate_legal_ir_document,
)
from ipfs_datasets_py.logic.bridge.registry import (
    logic_bridge_manifest,
    typed_bridge_contract_manifest,
    typed_bridge_contract_specs,
)
from ipfs_datasets_py.logic.bridge.schema import load_typed_bridge_schema
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_ROUNDTRIP_IR_INTERFACE,
    CANONICAL_TYPED_BRIDGE_INTERFACE,
    CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION,
    FORBIDDEN_BRIDGE_FAMILY_IDS,
    REGISTERED_BRIDGE_FAMILY_IDS,
    BridgeRepresentationKind,
    BridgeView,
    CanonicalAtomVocabulary,
    CanonicalContractError,
    CanonicalRoundTripIR,
    CanonicalRule,
    CanonicalTypedBridge,
    CompilerRequest,
    CompilerResult,
    ConstructDisposition,
    OperationStatus,
    RequiredBridgeConstruct,
    UnsupportedDisposition,
    UnsupportedSemantic,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes, cid_for_dag_json


def _rule() -> CanonicalRule:
    return CanonicalRule(
        modality="O",
        actor="agency",
        action="publish",
        object="notice",
        conditions=("request_received",),
        exceptions=("emergency",),
        temporal=(),
    )


def _canonical_ir() -> CanonicalRoundTripIR:
    return CanonicalRoundTripIR((_rule(),))


def _legal_document() -> LegalIRDocument:
    text = "Agency shall publish notice."
    return LegalIRDocument(
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
        frame_logic_triples=(
            {"subject": "agency", "predicate": "publish", "object": "notice"},
        ),
        metadata={"fixture": "pgir-020"},
    )


def _formalization_payload(domain: str = "security") -> dict[str, object]:
    return {
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
        "formulas": ({"formula_id": f"{domain}:formula", "view_id": f"{domain}.primary"},),
        "sample_id": f"{domain}:sample",
        "schema_version": "formalization-artifact/v1",
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


def test_required_construct_catalog_is_closed_and_complete() -> None:
    catalog = construct_catalog()
    required = required_bridge_constructs()

    assert required == tuple(item.value for item in RequiredBridgeConstruct)
    assert {item["construct_id"] for item in catalog["required_constructs"]} == set(required)
    assert "domain_logic_slice" in required
    assert "domain_logic_slice" not in catalog["registered_family_ids"]
    assert set(FORBIDDEN_BRIDGE_FAMILY_IDS) <= set(catalog["forbidden_family_ids"])
    assert set(REGISTERED_BRIDGE_FAMILY_IDS) == set(catalog["registered_family_ids"])
    assert is_forbidden_family_id("DomainLogicSlice") is True
    assert is_forbidden_family_id("deontic") is False


def test_domain_logic_slice_cannot_be_registered_as_a_family() -> None:
    view = BridgeView(
        name="canonical_roundtrip_ir",
        kind=BridgeRepresentationKind.CANONICAL_IR,
        schema_id=CANONICAL_ROUNDTRIP_IR_INTERFACE,
        family_id="canonical_roundtrip",
        payload=_canonical_ir().to_dict(),
    )
    with pytest.raises(CanonicalContractError, match="DomainLogicSlice"):
        CanonicalTypedBridge.compose(
            family_id="domain_logic_slice",
            authority_schema=CANONICAL_ROUNDTRIP_IR_INTERFACE,
            views=(view,),
        )
    with pytest.raises(CanonicalContractError, match="domain_logic_slice kind"):
        BridgeView(
            name="slice",
            kind=BridgeRepresentationKind.DOMAIN_LOGIC_SLICE,
            schema_id="bridge.domain_logic_slice",
            family_id="deontic",
            payload={"family_id": "deontic"},
        )


def test_wrap_canonical_ir_accounts_for_every_required_construct() -> None:
    ir = _canonical_ir()
    bridge = wrap_canonical_ir(
        ir,
        source_text="Agency shall publish notice unless an emergency applies.",
    )

    assert unexplained_constructs(bridge) == ()
    assert set(construct_coverage(bridge)) == set(required_bridge_constructs())
    assert bridge.family_identity.family_id == "canonical_roundtrip"
    assert extract_canonical_ir(bridge).ir_cid == ir.ir_cid
    assert bridge.construct_dispositions["canonical_ir"] is ConstructDisposition.REPRESENTED
    assert (
        bridge.construct_dispositions["domain_logic_slice"]
        is ConstructDisposition.EXPLICIT_PARTIAL
    )
    assert (
        bridge.construct_dispositions["formalization_artifact"]
        is ConstructDisposition.UNSUPPORTED
    )
    assert any(
        item.construct_id == "formalization_artifact"
        for item in bridge.unsupported_constructs
    )
    assert "domain_logic_slice" not in bridge.views
    assert bridge.domain_logic_slice.projection_payload()["slice_kind"] == (
        "domain_logic_slice"
    )
    assert bridge.domain_logic_slice.projection_payload()["family_id"] == (
        "canonical_roundtrip"
    )


def test_typed_bridge_identity_is_deterministic_and_wire_stable() -> None:
    first = wrap_canonical_ir(_canonical_ir(), source_text="Agency shall publish notice.")
    second = wrap_canonical_ir(_canonical_ir(), source_text="Agency shall publish notice.")
    wire = first.to_dict()

    assert first.bridge_cid == second.bridge_cid == cid_for_dag_json(first.identity_payload())
    assert CanonicalTypedBridge.from_dict(wire) == first
    assert wire["interface"] == CANONICAL_TYPED_BRIDGE_INTERFACE
    assert wire["schema_version"] == CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION

    tampered = copy.deepcopy(wire)
    tampered["adapter_name"] = "mutated-adapter"
    with pytest.raises(CanonicalContractError, match="bridge_cid"):
        CanonicalTypedBridge.from_dict(tampered)


def test_parallel_envelopes_are_retained_and_not_aliased() -> None:
    ir = _canonical_ir()
    document = _legal_document()
    artifact = _formalization_payload("legal")
    ir_bridge = wrap_canonical_ir(ir)
    document_bridge = wrap_legal_ir_document(document)
    artifact_bridge = wrap_formalization_artifact(artifact, family_id="legal")

    assert ir_bridge.family_identity.payload_cid != document_bridge.family_identity.payload_cid
    assert extract_canonical_ir(ir_bridge).to_dict() == ir.to_dict()
    assert extract_legal_ir_document(document_bridge)["document_id"] == document.document_id
    assert extract_formalization_artifact(artifact_bridge)["declaration_id"] == (
        artifact["declaration_id"]
    )
    assert "legal_ir_document" not in ir_bridge.views
    assert "canonical_roundtrip_ir" not in document_bridge.views
    assert document_bridge.family_identity.family_id == artifact_bridge.family_identity.family_id
    assert set(document_bridge.views).isdisjoint({"canonical_roundtrip_ir"})
    assert set(artifact_bridge.views).isdisjoint({"legal_ir_document"})


def test_wrap_compiler_result_retains_unsupported_semantics() -> None:
    ir = _canonical_ir()
    request = CompilerRequest(
        source_text="Agency shall publish notice.",
        request_id="bridge-test",
        atom_vocabulary=CanonicalAtomVocabulary(
            actors=("agency",),
            actions=("publish",),
            objects=("notice",),
            qualifiers=(),
        ),
    )
    result = CompilerResult(
        status=OperationStatus.SUCCESS,
        request_cid=request.request_cid,
        canonical_ir=ir,
        unsupported_semantics=(
            UnsupportedSemantic(
                code="caselaw.holding",
                message="Holding force is outside v1.",
                disposition=UnsupportedDisposition.EXPLICIT_PARTIAL,
                source_cid=request.source_cid,
                start=0,
                end=6,
            ),
        ),
        provenance={"arm_id": "typed_deontic"},
    )
    bridge = wrap_compiler_result(result, source_text=request.source_text)

    assert bridge.family_identity.family_id == "deontic"
    assert any(item.code == "caselaw.holding" for item in bridge.unsupported_constructs)
    assert extract_canonical_ir(bridge).ir_cid == ir.ir_cid
    assert bridge.metadata["compiler_result_cid"] == result.result_cid


def test_family_conformance_receipts_retain_identity_and_slice_role() -> None:
    receipts = family_conformance_receipts()
    families = {receipt.family_id for receipt in receipts}

    assert len(receipts) == len(family_conformance_vectors())
    assert families == {
        "canonical_roundtrip",
        "cec",
        "deontic",
        "intent",
        "legal",
        "modal",
        "security",
        "tdfol",
    }
    assert "domain_logic_slice" not in families
    for receipt in receipts:
        assert receipt.family_round_trip is True
        assert receipt.slice_is_not_family is True
        assert receipt.unexplained == ()
        assert receipt.slice_disposition in {"explicit_partial", "unsupported"}
        restored = evaluate_family_conformance(
            next(
                vector
                for vector in family_conformance_vectors()
                if vector.vector_id == receipt.vector_id
            )
        )
        assert restored.receipt_cid == receipt.receipt_cid


def test_migrations_are_lossless_and_identity_stable() -> None:
    ir = _canonical_ir()
    document = _legal_document()
    artifact = _formalization_payload("intent")

    ir_bridge, ir_receipt = migrate_canonical_ir(ir, source_text="Agency shall publish notice.")
    document_bridge, document_receipt = migrate_legal_ir_document(document)
    artifact_bridge, artifact_receipt = migrate_formalization_artifact(artifact)
    identity_bridge, identity_receipt = migrate_identity(ir_bridge)
    dispatched, dispatched_receipt = migrate_from_source(
        BridgeMigrationSource.CANONICAL_ROUNDTRIP_IR,
        ir,
        source_text="Agency shall publish notice.",
    )

    assert ir_receipt.lossless is True
    assert document_receipt.lossless is True
    assert artifact_receipt.lossless is True
    assert identity_receipt.lossless is True
    assert identity_bridge.bridge_cid == ir_bridge.bridge_cid
    assert dispatched.bridge_cid == ir_bridge.bridge_cid
    assert dispatched_receipt.source_schema == CANONICAL_ROUNDTRIP_IR_INTERFACE
    assert extract_canonical_ir(ir_bridge).ir_cid == ir.ir_cid
    assert extract_legal_ir_document(document_bridge)["citation"] == document.citation
    assert extract_formalization_artifact(artifact_bridge)["domain"] == "intent"
    exported_ir, exported_ir_receipt = export_canonical_ir(ir_bridge)
    exported_document, exported_document_receipt = export_legal_ir_document(document_bridge)
    exported_artifact, exported_artifact_receipt = export_formalization_artifact(artifact_bridge)
    assert exported_ir.ir_cid == ir.ir_cid
    assert exported_ir_receipt.lossless is True
    assert exported_document["document_id"] == document.document_id
    assert exported_document_receipt.lossless is True
    assert exported_artifact["declaration_id"] == artifact["declaration_id"]
    assert exported_artifact_receipt.lossless is True


def test_existing_adapter_registry_is_composed_without_new_families() -> None:
    adapter_records = adapter_conformance_records()
    manifest = logic_bridge_manifest()
    contracts = typed_bridge_contract_manifest()

    assert manifest["implemented_bridges"] == [
        "modal_frame_logic",
        "deontic_norms",
        "fol_tdfol",
        "cec_dcec",
        "external_prover_router",
        "zkp_attestation",
    ]
    assert [record["adapter_name"] for record in adapter_records] == manifest[
        "implemented_bridges"
    ]
    assert {spec.name for spec in typed_bridge_contract_specs()} == {
        "canonical_roundtrip_ir",
        "legal_ir_document",
        "formalization_artifact",
        "domain_logic_slice_role",
    }
    assert contracts["implemented_adapter_bridges"] == manifest["implemented_bridges"]
    slice_spec = next(
        spec for spec in typed_bridge_contract_specs() if spec.name == "domain_logic_slice_role"
    )
    assert slice_spec.representation_kind == "domain_logic_slice"
    assert slice_spec.family_id == "unspecified"
    by_name = {record["adapter_name"]: record for record in adapter_records}
    assert by_name["deontic_norms"]["family_registered"] is True
    assert by_name["external_prover_router"]["family_registered"] is False


def test_schema_golden_vectors_validate_against_packaged_schema() -> None:
    schema = load_typed_bridge_schema()
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(schema)

    vectors = schema_golden_vectors()
    assert {item["vector_id"] for item in vectors} == {
        vector.vector_id for vector in family_conformance_vectors()
    }
    for vector in family_conformance_vectors():
        bridge = build_conformance_bridge(vector)
        jsonschema.validate(bridge.to_dict(), schema)
        assert bridge.domain_logic_slice.family_id == vector.family_id


def test_semantic_mutation_changes_typed_bridge_identity() -> None:
    baseline = wrap_canonical_ir(_canonical_ir())
    mutated = wrap_canonical_ir(
        CanonicalRoundTripIR(
            (
                CanonicalRule(
                    modality="F",
                    actor="agency",
                    action="withhold",
                    object="notice",
                ),
            )
        )
    )

    assert baseline.bridge_cid != mutated.bridge_cid
    assert extract_canonical_ir(baseline).ir_cid != extract_canonical_ir(mutated).ir_cid
    assert baseline.family_identity.family_id == mutated.family_identity.family_id


def test_typed_syntax_kind_represents_the_typed_syntax_construct() -> None:
    document = _legal_document()
    bridge = wrap_legal_ir_document(document)

    assert bridge.construct_dispositions["typed_syntax"] is ConstructDisposition.REPRESENTED
    assert bridge.construct_dispositions["legal_ir_document"] is ConstructDisposition.REPRESENTED
    assert "typed_syntax" not in {
        item.construct_id for item in bridge.unsupported_constructs
    }
    assert unexplained_constructs(bridge) == ()


def test_wrap_formalization_artifact_accepts_to_dict_objects() -> None:
    class _Artifact:
        def to_dict(self) -> dict[str, object]:
            return _formalization_payload("intent")

    bridge = wrap_formalization_artifact(_Artifact(), family_id="intent")

    assert bridge.family_identity.family_id == "intent"
    assert extract_formalization_artifact(bridge)["domain"] == "intent"
    assert bridge.assumptions[0].assumption_id == "intent:isolated"
    assert bridge.source_references[0].ref_id == "source:intent"
