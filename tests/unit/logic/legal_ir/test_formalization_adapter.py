"""Compatibility tests for the Legal IR shared-formalization adapter."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.formalization.compiler import FormalizationArtifact
from ipfs_datasets_py.logic.formalization.samples import FormalizationSample
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_view_contracts import (
    LEGAL_IR_VIEW_CONTRACTS,
)
from ipfs_datasets_py.logic.ir_core.diagnostics import DiagnosticCode
from ipfs_datasets_py.logic.ir_core.provenance import SourceReviewStatus
from ipfs_datasets_py.logic.legal_ir.adapter import (
    LEGAL_IR_FORMALIZATION_ADAPTER_VERSION,
    LEGAL_IR_FORMALIZATION_VIEW_REGISTRY,
    LegalIRAdapter,
    LegalIRAdapterError,
    LegalIRFormalizationAdapter,
    adapt_legal_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIRFrameLogic,
    ModalIRFrameLogicTriple,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _reviewed_fixture(*, text: str | None = None) -> LegalSample:
    source_text = text or "Agency shall publish notice unless an emergency applies."
    start = source_text.index("Agency")
    modal = ModalIRDocument(
        document_id="us-code-5-552-fixture",
        source="us_code",
        normalized_text=source_text,
        formulas=[
            ModalIRFormula(
                formula_id="us-code-5-552-fixture:f0001",
                operator=ModalIROperator(
                    family="deontic",
                    system="D",
                    symbol="O",
                    label="obligation",
                ),
                predicate=ModalIRPredicate(
                    name="publish_notice",
                    arguments=["agency", "notice"],
                    role="clause",
                ),
                provenance=ModalIRProvenance(
                    source_id="us-code-5-552-fixture",
                    start_char=start,
                    end_char=len(source_text),
                    citation="5 U.S.C. 552",
                ),
                conditions=["request_received"],
                exceptions=["emergency"],
                metadata={"legal_scope": "agency_records"},
            )
        ],
        frame_logic=ModalIRFrameLogic(
            selected_frame="administrative_notice",
            graph_id="legal-graph-552",
            triples=[
                ModalIRFrameLogicTriple(
                    subject="agency",
                    predicate="must_publish",
                    object="notice",
                )
            ],
            metadata={"legal_relation_scope": "section_552"},
        ),
        metadata={
            "citation": "5 U.S.C. 552",
            "deterministic_parser": "reviewed_fixture_v1",
        },
    )
    sample = LegalSample(
        sample_id="us-code-5-552-fixture",
        source="us_code",
        title="5",
        section="552",
        citation="5 U.S.C. 552",
        text=source_text,
        normalized_text=source_text,
        embedding_model="fixture:embedding-v1",
        embedding_vector=[0.25, -0.5],
        modal_ir=modal,
        frame_candidates=[
            {
                "domain": "administrative",
                "frame_id": "administrative_notice",
                "label": "Administrative notice",
                "score": 1.0,
            }
        ],
        selected_frame="administrative_notice",
        parser_trace={"parser": "reviewed_fixture_v1"},
        losses={"reconstruction_loss": 0.125},
    )
    sample.validate()
    return sample


def test_registry_preserves_every_canonical_legal_view_and_alias() -> None:
    adapter = LegalIRFormalizationAdapter()

    assert isinstance(adapter, LegalIRAdapter)
    assert LEGAL_IR_FORMALIZATION_VIEW_REGISTRY.view_ids == tuple(
        sorted(LEGAL_IR_VIEW_CONTRACTS.contract_ids)
    )
    for contract in LEGAL_IR_VIEW_CONTRACTS.contracts():
        shared = adapter.view_registry.resolve(contract.contract_id)
        assert shared.metadata["canonical_legal_view"] == contract.view.value
        assert shared.metadata["aliases"] == tuple(contract.aliases)
        assert shared.metadata["target_component"] == contract.target_component
        assert adapter.view_aliases[contract.contract_id] == (
            contract.view.value,
            contract.target_component,
            *contract.aliases,
        )


def test_adapt_sample_is_grounded_source_free_and_preserves_legacy_identity() -> None:
    legal = _reviewed_fixture()
    adapter = LegalIRFormalizationAdapter(
        source_review_status=SourceReviewStatus.TRUSTED_FIXTURE
    )
    sample = adapter.adapt_sample(legal)
    payload = sample.payload.to_dict()
    legacy_hash = legal.modal_ir.canonical_hash()

    assert isinstance(sample, FormalizationSample)
    assert sample.domain == "legal"
    assert sample.declaration_digest == f"sha256:{legacy_hash}"
    assert adapter.existing_output_identity(legal) == legacy_hash
    assert sample.metadata["legacy_output_identity"] == legacy_hash
    assert payload["legacy_output_identity"]["hexdigest"] == legacy_hash
    assert payload["legal_document"]["modal_ir"] == {
        key: value
        for key, value in legal.modal_ir.to_dict().items()
        if key != "normalized_text"
    }
    assert "text" not in payload["legal_document"]
    assert "embedding_vector" not in payload["legal_document"]
    assert sample.provenance.sources[0].content_sha256 != legacy_hash
    assert (
        sample.provenance.sources[0].content_sha256
        == hashlib.sha256(legal.text.encode("utf-8")).hexdigest()
    )
    assert sample.provenance.sources[0].review_status is SourceReviewStatus.TRUSTED_FIXTURE
    assert FormalizationSample.from_json(sample.to_json()) == sample


def test_complete_adaptation_conforms_to_shared_and_legal_view_contracts() -> None:
    legal = _reviewed_fixture()
    adapter = LegalIRFormalizationAdapter()
    artifact = adapter.adapt(legal)
    legacy_hash = legal.modal_ir.canonical_hash()
    deontic = next(
        formula
        for formula in artifact.formulas
        if formula.view_id == "legal-ir-view/deontic/v1"
    )
    frame = next(
        formula
        for formula in artifact.formulas
        if formula.view_id == "legal-ir-view/frame-logic/v1"
    )

    assert isinstance(artifact, FormalizationArtifact)
    assert artifact.declaration_digest == f"sha256:{legacy_hash}"
    assert artifact.metadata["legacy_output_identity"] == legacy_hash
    assert artifact.metadata["legacy_modal_ir_canonical_hash"] == legacy_hash
    assert deontic.formula_id == legal.modal_ir.formulas[0].formula_id
    assert (
        deontic.to_dict()["expression"]["legal_modal_ir"]
        == legal.modal_ir.formulas[0].to_dict()
    )
    assert deontic.opaque is False
    assert (
        frame.to_dict()["expression"]["legal_frame_logic"]
        == legal.modal_ir.frame_logic.to_dict()
    )
    assert frame.opaque is False
    assert LEGAL_IR_VIEW_CONTRACTS.validate(
        "deontic", deontic.expression
    ).valid
    assert LEGAL_IR_VIEW_CONTRACTS.validate(
        "frame_logic", frame.expression
    ).valid
    assert artifact.cross_view_links[0].relation.value == "corresponds_to"
    assert FormalizationArtifact.from_json(artifact.to_json()) == artifact
    assert adapt_legal_sample(legal).declaration_digest == artifact.declaration_digest


def test_unsupported_legal_fields_are_explicit_grounded_and_content_bound() -> None:
    legal = _reviewed_fixture()
    adapter = LegalIRFormalizationAdapter()
    persisted = legal.to_dict()
    persisted["court_specific_extension"] = {"standard": "strict_scrutiny"}
    sample = adapter.adapt_sample(persisted)
    artifact = adapter.compile(sample, adapter.default_config(sample))
    manifest = {
        item["field_path"]: item
        for item in sample.payload.to_dict()["unsupported_fields"]
    }
    diagnostic_paths = {
        item.location.field_path for item in artifact.unsupported_diagnostics
    }

    assert {
        "/text",
        "/normalized_text",
        "/modal_ir/normalized_text",
        "/embedding_model",
        "/embedding_vector",
        "/parser_trace",
        "/losses",
        "/court_specific_extension",
    }.issubset(manifest)
    assert manifest["/losses"]["disposition"] == "unsupported_runtime_result"
    assert manifest["/embedding_vector"]["content_digest"].startswith("sha256:")
    assert set(manifest).issubset(diagnostic_paths)
    assert all(
        diagnostic.code == DiagnosticCode.UNSUPPORTED_FEATURE.value
        and diagnostic.location.traceable
        for diagnostic in artifact.unsupported_diagnostics
    )


def test_unicode_legal_character_spans_are_converted_to_exact_byte_spans() -> None:
    legal = _reviewed_fixture(text="§ 😀 Agency shall publish notice.")
    sample = LegalIRFormalizationAdapter().adapt_sample(legal)
    formula_span = next(
        span
        for span in sample.provenance.spans
        if span.metadata.get("legacy_formula_id")
    )
    start_char = legal.text.index("Agency")

    assert formula_span.start_char == start_char
    assert formula_span.start_byte == len(legal.text[:start_char].encode("utf-8"))
    assert formula_span.end_byte == len(legal.text.encode("utf-8"))


def test_normalized_offsets_are_not_misrepresented_as_exact_raw_offsets() -> None:
    legal = _reviewed_fixture()
    persisted = legal.to_dict()
    persisted["text"] = "Agency   shall publish notice unless an emergency applies."
    sample = LegalIRFormalizationAdapter().adapt_sample(persisted)
    formula_span = next(
        span
        for span in sample.provenance.spans
        if span.metadata.get("legacy_formula_id")
    )
    unsupported_paths = {
        item["field_path"]
        for item in sample.payload.to_dict()["unsupported_fields"]
    }

    assert formula_span.start_byte == 0
    assert formula_span.end_byte == len(persisted["text"].encode("utf-8"))
    assert formula_span.metadata["coordinate_alignment"] == "whole_source"
    assert "/modal_ir/formulas/*/provenance" in unsupported_paths


def test_adapter_rejects_unreviewed_or_internally_inconsistent_legal_inputs() -> None:
    with pytest.raises(LegalIRAdapterError, match="reviewed"):
        LegalIRFormalizationAdapter(
            source_review_status=SourceReviewStatus.UNREVIEWED
        )

    legal = _reviewed_fixture()
    corrupted = legal.to_dict()
    corrupted["modal_ir"]["normalized_text"] = "different"
    with pytest.raises(LegalIRAdapterError, match="normalized_text"):
        LegalIRFormalizationAdapter().adapt_sample(corrupted)

    corrupted = legal.to_dict()
    corrupted["modal_ir"]["formulas"][0]["provenance"]["end_char"] = len(legal.text) + 1
    with pytest.raises(LegalIRAdapterError, match="outside source text"):
        LegalIRFormalizationAdapter().adapt_sample(corrupted)

    adapted = LegalIRFormalizationAdapter().adapt_sample(legal)
    with pytest.raises(LegalIRAdapterError, match="Legal FormalizationSample"):
        LegalIRFormalizationAdapter().compile(
            replace(adapted, domain="security"),
            LegalIRFormalizationAdapter().default_config(adapted),
        )


def test_adapter_schema_version_is_exposed_on_every_shared_output() -> None:
    legal = _reviewed_fixture()
    adapter = LegalIRFormalizationAdapter()
    sample = adapter.to_formalization_sample(legal)
    artifact = adapter.adapt_artifact(legal)

    assert (
        sample.payload["adapter_schema_version"]
        == LEGAL_IR_FORMALIZATION_ADAPTER_VERSION
    )
    assert (
        artifact.metadata["adapter_schema_version"]
        == LEGAL_IR_FORMALIZATION_ADAPTER_VERSION
    )


def test_custom_generic_config_explains_unemitted_views_and_empty_producer() -> None:
    adapter = LegalIRFormalizationAdapter()
    sample = adapter.adapt_sample(_reviewed_fixture())
    config = replace(
        adapter.default_config(sample),
        producer_id="",
        target_view_ids=(
            "legal-ir-view/deontic/v1",
            "legal-ir-view/external-provers/v1",
            "legal-ir-view/frame-logic/v1",
        ),
    )
    artifact = adapter.compile(sample, config)

    missing_view_diagnostic = next(
        item
        for item in artifact.unsupported_diagnostics
        if item.metadata.get("view_id") == "legal-ir-view/external-provers/v1"
    )
    assert "emits no formula" in missing_view_diagnostic.message
    assert missing_view_diagnostic.producer_id == adapter.producer_id
    assert artifact.compiler_config.producer_id == ""
