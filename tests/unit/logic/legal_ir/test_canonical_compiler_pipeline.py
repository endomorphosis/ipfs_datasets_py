"""Golden traces, replay, source-map, and invalid-input tests for PGIR-021."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_canonical_adapter import (
    CANONICAL_COMPILER_AUTHORITY_ID,
    compile_legal_ir_canonical,
    compile_through_canonical_authority,
    compiler_request_from_legal_ir_source,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_compiler_api import (
    compile_legal_ir,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_canonical_pipeline import (
    CANONICAL_COMPILER_PIPELINE_CID,
    CANONICAL_COMPILER_PIPELINE_INTERFACE,
    CANONICAL_COMPILER_STAGE_IDS,
    CANONICAL_COMPILER_STAGE_INTERFACES,
    CompilerStageRecord,
    compile_canonical_pipeline,
    compiler_pipeline_configuration,
    replay_compiler_pipeline,
    replay_compiler_stage,
)
from ipfs_datasets_py.logic.legal_ir.canonical_compiler import (
    TYPED_DEONTIC_COMPILER_CONFIG_CID,
    TypedDeonticCanonicalCompiler,
)
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE,
    CanonicalAtomVocabulary,
    CanonicalContractError,
    CompilerRequest,
    OperationStatus,
    UnsupportedDisposition,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json, validate_cid


def _vocabulary() -> CanonicalAtomVocabulary:
    return CanonicalAtomVocabulary(
        actors=("agency", "company_a"),
        actions=("file", "submit", "withdraw"),
        objects=("backup_report", "notice"),
        qualifiers=("emergency", "natural_disaster", "within_10_days"),
    )


def _request(
    source_text: str = "Company A shall submit backup report within 10 days unless emergency.",
    *,
    allow_explicit_partial: bool = False,
    config: dict[str, object] | None = None,
) -> CompilerRequest:
    return CompilerRequest(
        source_text=source_text,
        request_id="pipeline-test",
        atom_vocabulary=_vocabulary(),
        allow_explicit_partial=allow_explicit_partial,
        config={} if config is None else config,
    )


def test_pipeline_stage_identities_are_frozen_and_replayable() -> None:
    table = compiler_pipeline_configuration()
    assert table["interface"] == CANONICAL_COMPILER_PIPELINE_INTERFACE
    assert cid_for_dag_json(table) == CANONICAL_COMPILER_PIPELINE_CID
    assert tuple(item["stage_id"] for item in table["stages"]) == CANONICAL_COMPILER_STAGE_IDS
    assert CANONICAL_COMPILER_STAGE_INTERFACES["target"].startswith("TypedDeontic")


def test_successful_compile_emits_golden_stage_trace() -> None:
    request = _request()
    first = compile_canonical_pipeline(request)
    second = replay_compiler_pipeline(request)

    assert first.result.status is OperationStatus.SUCCESS
    assert first.result.result_cid == second.result.result_cid
    assert [item.stage_id for item in first.stages] == list(CANONICAL_COMPILER_STAGE_IDS)
    assert [item.identity_cid for item in first.stages] == [
        item.identity_cid for item in second.stages
    ]
    for record in first.stages:
        validate_cid(record.input_cid, codecs=("dag-json",))
        validate_cid(record.output_cid, codecs=("dag-json",))
        validate_cid(record.identity_cid, codecs=("dag-json",))
        assert record.interface == CANONICAL_COMPILER_STAGE_INTERFACES[record.stage_id]
        assert record.status == "success"
        replayed = replay_compiler_stage(record.stage_id, request)
        assert replayed.identity_cid == record.identity_cid

    assert first.pipeline_cid == CANONICAL_COMPILER_PIPELINE_CID
    assert first.result.canonical_ir is not None
    assert first.stage("bridge").output_cid
    assert first.stage("formalization").output_cid
    assert first.stage("target").output_cid
    assert (
        TypedDeonticCanonicalCompiler().compile(request).canonical_ir.ir_cid
        == first.result.canonical_ir.ir_cid
    )
    slice_unsupported = first.stage("domain_slice_adapter").unsupported
    assert slice_unsupported
    assert all("domain_logic_slice" in item["construct_id"] for item in slice_unsupported)


def test_source_map_is_deterministic_and_bound_to_selected_span() -> None:
    request = _request()
    result = TypedDeonticCanonicalCompiler().compile(request)
    receipt = result.source_map_receipt()
    assert receipt is not None
    body = dict(receipt)
    receipt_cid = body.pop("receipt_cid")
    assert receipt_cid == cid_for_dag_json(body)
    selection = compile_canonical_pipeline(request).stage("source_selection")
    assert result.source_map
    for entry in result.source_map:
        assert entry.source_cid == request.source_cid
        assert 0 <= entry.start < entry.end <= len(request.source_text)
        assert entry.attribution == "coarse:typed_deontic_record_span"
    replayed = TypedDeonticCanonicalCompiler().compile(request)
    assert replayed.source_map == result.source_map
    assert replayed.result_cid == result.result_cid
    validate_cid(selection.output_cid, codecs=("dag-json",))


def test_invalid_inputs_fail_closed_without_fabricating_ir() -> None:
    compiler = TypedDeonticCanonicalCompiler()
    with pytest.raises(CanonicalContractError, match="CompilerRequest"):
        compiler.compile(object())  # type: ignore[arg-type]

    invalid = compiler.compile(_request(config={"use_ml": True}))
    assert invalid.status is OperationStatus.FAILED
    assert invalid.error is not None
    assert invalid.error.code.value == "invalid_request"
    assert invalid.canonical_ir is None
    assert invalid.component_trace == ()
    assert invalid.provenance["model_call_count"] == 0
    assert invalid.provenance["fallback_used"] is False

    empty = compiler.compile(_request("This paragraph contains no normative rule."))
    assert empty.status is OperationStatus.FAILED
    assert empty.error is not None
    assert empty.error.code.value == "empty_output"
    assert empty.canonical_ir is None
    assert not empty.source_map
    empty_pipeline = compile_canonical_pipeline(
        _request("This paragraph contains no normative rule.")
    )
    assert [item.stage_id for item in empty_pipeline.stages] == [
        "source_selection",
        "typed_family_parse",
    ]

    with pytest.raises(CanonicalContractError, match="unknown compiler pipeline stage"):
        replay_compiler_stage("not_a_stage", _request())

    with pytest.raises(CanonicalContractError, match="unknown compiler pipeline stage"):
        CompilerStageRecord(
            stage_id="not_a_stage",
            interface="x",
            input_cid=_request().request_cid,
            output_cid=_request().request_cid,
            config_cid=TYPED_DEONTIC_COMPILER_CONFIG_CID,
            status="success",
        )


def test_unmapped_semantics_are_recorded_on_elaboration_stage() -> None:
    source = "Company A shall submit backup report. Unknown party must invent widgets."
    pipeline = compile_canonical_pipeline(_request(source, allow_explicit_partial=True))

    assert pipeline.result.status is OperationStatus.SUCCESS
    elaboration = pipeline.stage("elaboration")
    assert elaboration.unsupported
    assert all(
        item.disposition is UnsupportedDisposition.EXPLICIT_PARTIAL
        for item in pipeline.result.unsupported_semantics
    )
    abstained = compile_canonical_pipeline(_request(source))
    assert abstained.result.status is OperationStatus.ABSTAINED
    assert abstained.stage("elaboration").unsupported
    assert abstained.result.canonical_ir is None


def test_legal_ir_surfaces_delegate_to_canonical_authority() -> None:
    compatibility = compile_legal_ir(
        {
            "citation": "42 U.S.C. 1983(a)",
            "raw_document": "The agency shall disclose records within 30 days.",
            "source_document_id": "doc-api",
        }
    )
    authority = compatibility.payload["canonical_authority"]
    assert authority["authority"] == CANONICAL_STRUCTURED_TEXT_COMPILER_INTERFACE
    assert authority["compiler"] == CANONICAL_COMPILER_AUTHORITY_ID
    assert authority["configuration_cid"] == TYPED_DEONTIC_COMPILER_CONFIG_CID
    assert authority["delegated"] is False
    assert authority["reason"] == "compatibility_adapter_without_compiler_request"
    assert compatibility.payload["compiled"]["canonical_authority"]["delegated"] is False

    request = _request()
    assert compiler_request_from_legal_ir_source(request) == request
    delegated = compile_legal_ir(
        {
            "allow_explicit_partial": False,
            "atom_vocabulary": _vocabulary().to_dict(),
            "raw_document": request.source_text,
            "request_id": "pipeline-test",
        }
    )
    delegated_authority = delegated.payload["canonical_authority"]
    assert delegated_authority["delegated"] is True
    assert delegated_authority["reason"] == "delegated_to_canonical_compiler"
    assert delegated.payload["canonical_compile"]["status"] == "success"
    assert delegated.payload["canonical_compile"]["canonical_ir_cid"]

    direct = compile_legal_ir_canonical(request)
    through, record = compile_through_canonical_authority(request)
    assert through is not None
    assert direct.result_cid == through.result_cid
    assert record["delegated"] is True

    with pytest.raises(CanonicalContractError, match="cannot form CompilerRequest"):
        compile_legal_ir_canonical({"raw_document": request.source_text})
