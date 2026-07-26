"""Synthetic revision-2 semantic validator and calibration regressions.

These tests inject source text and reviewed targets directly.  They never
load the combined benchmark corpus or inspect a holdout fixture.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL_SHA256,
    SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID,
    SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID,
    SEMANTIC_FAILURE_SCHEMA_V2,
    SEMANTIC_PRODUCER_REGISTRY_V2_CID,
    SEMANTIC_PROTOCOL_V2_CID,
    SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID,
    STAGE_PROVENANCE_SCHEMA,
    CacheMode,
    FailureCode,
    SemanticProjection,
    Split,
    StageName,
    StageProvenance,
    StageRecord,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)
from benchmarks.logic_pipeline.semantic_reassessment import (
    SemanticCalibrationCoordinateV2,
    SemanticCalibrationGraphBindingV2,
    SemanticCalibrationTargetV2,
    SemanticReassessmentError,
    evaluate_semantic_calibration_coordinate_v2,
    evaluate_semantic_calibration_v2,
    validate_semantic_frontend_stage_v2,
)


_RUN_ID = "synthetic-semantic-v2"
_MANIFEST_SHA256 = "a" * 64
_ENVIRONMENT_SHA256 = "e" * 64


def _target(
    *,
    case_id: str = "synthetic-001",
) -> SemanticCalibrationTargetV2:
    return SemanticCalibrationTargetV2(
        case_id=case_id,
        source_text="An agency must publish the notice.",
        logic_family="deontic",
        target="publish_notice",
        semantic_class="proved",
        predicates=("publish_notice",),
        entities=("agency", "notice"),
    )


def _input_sha256(source_text: str) -> str:
    return hashlib.sha256(
        canonical_json({"text": source_text}).encode("utf-8")
    ).hexdigest()


def _identity(
    source_text: str,
    *,
    stage: StageName,
    producer_id: str,
) -> dict[str, object]:
    value: dict[str, object] = {
        "graph_invoked": True,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "source_cid": cid_for_bytes(source_text.encode("utf-8")),
        "proof_context_cid": None,
    }
    if stage is StageName.SPACY:
        value["mode"] = {
            "spacy_full_model": "full_model",
            "spacy_regex_legal": "regex_legal",
            "spacy_blank_model": "blank_model",
        }[producer_id]
    return value


def _record(
    target: SemanticCalibrationTargetV2,
    *,
    producer_id: str,
    payload: object,
    status: StageStatus = StageStatus.SUCCESS,
    failure_code: FailureCode | None = None,
    failure_detail: str | None = None,
    input_sha256: str | None = None,
) -> StageRecord:
    stage = (
        StageName.COMPILER
        if producer_id == "compiler"
        else (
            StageName.SYMAI
            if producer_id == "symai"
            else StageName.SPACY
        )
    )
    identity = _identity(
        target.source_text,
        stage=stage,
        producer_id=producer_id,
    )
    provenance = StageProvenance(
        schema=STAGE_PROVENANCE_SCHEMA,
        adapter_id=f"{stage.value}-adapter",
        adapter_version="2",
        source=("synthetic_fixture",),
        requested_identity=identity,
        effective_identity=identity,
        input_sha256=(
            _input_sha256(target.source_text)
            if input_sha256 is None
            else input_sha256
        ),
        environment_sha256=_ENVIRONMENT_SHA256,
    )
    return StageRecord.create(
        protocol_sha256=DEFAULT_PROTOCOL_SHA256,
        run_id=_RUN_ID,
        case_id=target.case_id,
        case_manifest_sha256=_MANIFEST_SHA256,
        variant_id="A0",
        split=Split.PILOT,
        cache_mode=CacheMode.COLD,
        stage=stage,
        adapter_version="2",
        status=status,
        provenance=provenance,
        telemetry=TelemetryRecord(),
        data=payload,
        failure_code=failure_code,
        failure_detail=failure_detail,
    )


def _projection_payload(
    target: SemanticCalibrationTargetV2,
    producer_id: str,
    *,
    correct: bool = True,
    extra_terms: bool = False,
    ambiguity_flags: tuple[str, ...] = (),
    validation_errors: tuple[str, ...] = (),
) -> tuple[dict[str, object], SemanticProjection]:
    stage = (
        StageName.COMPILER
        if producer_id == "compiler"
        else (
            StageName.SYMAI
            if producer_id == "symai"
            else StageName.SPACY
        )
    )
    semantics = {
        "logic_family": target.logic_family if correct else "fol",
        "target": target.target if correct else "deny_notice",
        "semantic_class": (
            target.semantic_class if correct else "disproved"
        ),
        "predicates": (
            (
                (*target.predicates, "unreviewed_extra_predicate")
                if extra_terms
                else target.predicates
            )
            if correct
            else ("deny_notice",)
        ),
        "entities": (
            (
                (*target.entities, "unreviewed_extra_entity")
                if extra_terms
                else target.entities
            )
            if correct
            else ("other_actor",)
        ),
    }
    completeness = {
        "logic_family": True,
        "target": True,
        "class": True,
        "predicates": True,
        "entities": True,
    }
    if stage in {StageName.COMPILER, StageName.SPACY}:
        modal_ir = {
            "formulas": [
                {
                    "operator": {"family": semantics["logic_family"]},
                    "predicate": {
                        "name": semantics["target"],
                        "arguments": list(semantics["entities"]),
                    },
                }
            ]
        }
        evidence_cid = cid_for_dag_json(modal_ir)
    else:
        response = {
            "logic_family": semantics["logic_family"],
            "target": semantics["target"],
            "class": semantics["semantic_class"],
            "predicates": list(semantics["predicates"]),
            "entities": list(semantics["entities"]),
            "completeness": completeness,
            "ambiguity_flags": list(ambiguity_flags),
            "confidence_millionths": 900_000,
            "validation_errors": list(validation_errors),
        }
        evidence_cid = cid_for_dag_json(response)
    projection = SemanticProjection.create(
        producer_id=producer_id,
        source_text=target.source_text,
        logic_family=str(semantics["logic_family"]),
        target=str(semantics["target"]),
        semantic_class=str(semantics["semantic_class"]),
        predicates=semantics["predicates"],
        entities=semantics["entities"],
        completeness=completeness,
        ambiguity_flags=ambiguity_flags,
        confidence_millionths=900_000,
        validation_errors=validation_errors,
        evidence_cid=evidence_cid,
    )
    if stage is StageName.COMPILER:
        return {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v2"
            ),
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "source_cid": target.source_cid,
            "modal_ir": modal_ir,
            "modal_ir_cid": evidence_cid,
            "retained_modal_ir_cid": evidence_cid,
            "semantic_projection": projection.to_dict(),
        }, projection
    if stage is StageName.SPACY:
        return {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark.spacy-evidence.v2"
            ),
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "document": {"source_cid": target.source_cid},
            "modal_ir": modal_ir,
            "modal_ir_cid": evidence_cid,
            "semantic_projection": projection.to_dict(),
        }, projection
    raw_output = canonical_json(response)
    return {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark.symai-evidence.v2"
        ),
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "source_cid": target.source_cid,
        "raw_output": raw_output,
        "raw_output_cid": cid_for_bytes(raw_output.encode("utf-8")),
        "validated_response": response,
        "validated_response_cid": evidence_cid,
        "semantic_projection": projection.to_dict(),
    }, projection


def _coordinate(
    target: SemanticCalibrationTargetV2,
    producer_id: str,
    *,
    correct: bool = True,
) -> SemanticCalibrationCoordinateV2:
    payload, _projection = _projection_payload(
        target,
        producer_id,
        correct=correct,
    )
    return SemanticCalibrationCoordinateV2(
        case_id=target.case_id,
        producer_id=producer_id,
        stages=(
            _record(
                target,
                producer_id=producer_id,
                payload=payload,
            ),
        ),
    )


def _symai_failure(
    target: SemanticCalibrationTargetV2,
    subcode: str,
) -> StageRecord:
    body = {
        "schema": SEMANTIC_FAILURE_SCHEMA_V2,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "stage": "symai",
        "failure_subcode": subcode,
        "source_cid": target.source_cid,
        "proof_context_cid": None,
        "evidence": {
            "raw_output_cid": None,
            "raw_output_bytes": None,
        },
    }
    receipt = {**body, "receipt_cid": cid_for_dag_json(body)}
    payload = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark.symai-evidence.v2"
        ),
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "raw_output": None,
        "raw_output_cid": None,
        "raw_output_bytes": None,
        "raw_output_retained_exactly": False,
        "semantic_projection": None,
        "semantic_failure": receipt,
    }
    return _record(
        target,
        producer_id="symai",
        payload=payload,
        status=StageStatus.FAILED,
        failure_code=FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE,
        failure_detail="synthetic semantic failure",
    )


def test_v2_compares_same_shaped_semantics_and_validates_evidence_cids() -> None:
    target = _target()
    coordinate = _coordinate(target, "compiler")

    receipt = evaluate_semantic_calibration_coordinate_v2(
        target,
        coordinate,
    )
    parsed = validate_semantic_frontend_stage_v2(
        coordinate.stages[0],
        target.source_text,
    )

    assert receipt["status"] == "semantically_correct"
    assert parsed is not None
    assert parsed.producer_id == "compiler"
    assert receipt["quality_millionths"] == 1_000_000
    assert receipt["expected_semantics"] == receipt["observed_semantics"]
    assert receipt["raw_evidence_cid_compared_to_reviewed_ir"] is False
    assert str(receipt["projection_cid"]).startswith("b")
    assert str(receipt["semantic_content_cid"]).startswith("b")
    assert receipt["terminal_stage_cid"] == cid_for_dag_json(
        json.loads(canonical_json(coordinate.stages[0].to_dict()))
    )

    payload = coordinate.stages[0].to_dict()["data"]
    assert isinstance(payload, dict)
    payload["retained_modal_ir_cid"] = cid_for_dag_json(
        {"tampered": True}
    )
    tampered = SemanticCalibrationCoordinateV2(
        case_id=target.case_id,
        producer_id="compiler",
        stages=(
            _record(
                target,
                producer_id="compiler",
                payload=payload,
            ),
        ),
    )
    with pytest.raises(
        SemanticReassessmentError,
        match="full or retained ModalIR CID binding mismatched",
    ):
        evaluate_semantic_calibration_coordinate_v2(target, tampered)


def test_compiler_cid_only_projection_validates_every_nested_identity() -> None:
    target = _target()
    payload, projection = _projection_payload(target, "compiler")
    retained = {
        "document_id": target.case_id,
        "normalized_text_cid": cid_for_dag_json(target.source_text),
        "formulas_cid": projection.evidence_cid,
        "source": "synthetic",
        "version": "2",
        "projection": "cid_only",
    }
    payload["modal_ir"] = retained
    payload["retained_modal_ir_cid"] = cid_for_dag_json(retained)
    record = _record(
        target,
        producer_id="compiler",
        payload=payload,
    )

    assert validate_semantic_frontend_stage_v2(
        record, target.source_text
    ) == projection
    receipt = evaluate_semantic_calibration_coordinate_v2(
        target,
        SemanticCalibrationCoordinateV2(
            case_id=target.case_id,
            producer_id="compiler",
            stages=(record,),
        ),
    )
    assert receipt["status"] == "semantic_schema_incompatible"
    assert receipt["quality_millionths"] is None

    for field, invalid in (
        ("normalized_text_cid", "not-a-cid"),
        ("formulas_cid", cid_for_bytes(b"wrong-codec")),
        ("unexpected", "extra-field"),
    ):
        tampered_payload = dict(payload)
        tampered_retained = dict(retained)
        tampered_retained[field] = invalid
        tampered_payload["modal_ir"] = tampered_retained
        tampered_payload["retained_modal_ir_cid"] = cid_for_dag_json(
            tampered_retained
        )
        with pytest.raises(SemanticReassessmentError):
            validate_semantic_frontend_stage_v2(
                _record(
                    target,
                    producer_id="compiler",
                    payload=tampered_payload,
                ),
                target.source_text,
            )


def test_exact_five_field_quality_rejects_unreviewed_extra_terms() -> None:
    target = _target()
    payload, _projection = _projection_payload(
        target,
        "symai",
        extra_terms=True,
    )
    receipt = evaluate_semantic_calibration_coordinate_v2(
        target,
        SemanticCalibrationCoordinateV2(
            case_id=target.case_id,
            producer_id="symai",
            stages=(
                _record(
                    target,
                    producer_id="symai",
                    payload=payload,
                ),
            ),
        ),
    )

    assert receipt["status"] == "semantically_incorrect"
    assert receipt["quality_millionths"] == 0
    assert receipt["field_matches"]["predicates"] is False
    assert receipt["field_matches"]["entities"] is False


def test_unretained_full_compiler_block_is_not_calibration_authority() -> None:
    target = _target()
    payload, _projection = _projection_payload(target, "compiler")
    retained_projection = {"formulas": []}
    payload["modal_ir"] = retained_projection
    payload["retained_modal_ir_cid"] = cid_for_dag_json(
        retained_projection
    )
    coordinate = SemanticCalibrationCoordinateV2(
        case_id=target.case_id,
        producer_id="compiler",
        stages=(
            _record(
                target,
                producer_id="compiler",
                payload=payload,
            ),
        ),
    )

    receipt = evaluate_semantic_calibration_coordinate_v2(
        target,
        coordinate,
    )

    assert receipt["status"] == "semantic_schema_incompatible"
    assert receipt["quality_millionths"] is None
    assert (
        receipt["evidence_verification"][
            "projection_evidence_cid_recomputed"
        ]
        is False
    )
    assert (
        receipt["evidence_verification"][
            "retained_evidence_cid_recomputed"
        ]
        is True
    )
    assert (
        receipt["semantic_evidence_authoritative_for_calibration"]
        is False
    )
    assert receipt["eligible_for_complete_calibration"] is False

    targets = tuple(
        _target(case_id=f"compiler-sidecar-{index:03d}")
        for index in range(20)
    )
    coordinates = []
    for item in targets:
        truncated_payload, _ = _projection_payload(item, "compiler")
        truncated_payload["modal_ir"] = retained_projection
        truncated_payload["retained_modal_ir_cid"] = cid_for_dag_json(
            retained_projection
        )
        coordinates.append(
            SemanticCalibrationCoordinateV2(
                case_id=item.case_id,
                producer_id="compiler",
                stages=(
                    _record(
                        item,
                        producer_id="compiler",
                        payload=truncated_payload,
                    ),
                ),
            )
        )
        coordinates.extend(
            _coordinate(item, producer_id)
            for producer_id in (
                "spacy_full_model",
                "spacy_regex_legal",
                "spacy_blank_model",
                "symai",
            )
        )
    report = evaluate_semantic_calibration_v2(
        targets=targets,
        coordinates=tuple(coordinates),
    )

    assert report["status"] == "semantic_schema_incompatible"
    assert report["quality"]["semantic_quality_rate"] is None
    assert report["absolute_quality_gate"]["passed"] is False
    assert report["relative_selection"]["selected_producer_ids"] == []


def test_every_invoked_frontend_must_bind_exact_source_only_input() -> None:
    target = _target()
    compiler_payload, _ = _projection_payload(target, "compiler")
    spacy_payload, _ = _projection_payload(
        target,
        "spacy_regex_legal",
    )
    unsafe_sha256 = hashlib.sha256(
        canonical_json(
            {
                "text": target.source_text,
                "expected_class": target.semantic_class,
            }
        ).encode("utf-8")
    ).hexdigest()
    coordinate = SemanticCalibrationCoordinateV2(
        case_id=target.case_id,
        producer_id="spacy_regex_legal",
        stages=(
            _record(
                target,
                producer_id="compiler",
                payload=compiler_payload,
            ),
            _record(
                target,
                producer_id="spacy_regex_legal",
                payload=spacy_payload,
                input_sha256=unsafe_sha256,
            ),
        ),
    )

    with pytest.raises(
        SemanticReassessmentError,
        match="exact canonical source-only envelope",
    ):
        evaluate_semantic_calibration_coordinate_v2(target, coordinate)


def test_spacy_mode_identity_and_upstream_projection_producer_are_exact() -> None:
    target = _target()
    full_payload, _ = _projection_payload(target, "spacy_full_model")
    full_stage = _record(
        target,
        producer_id="spacy_full_model",
        payload=full_payload,
    )
    mismatched_identity = replace(
        full_stage,
        provenance=replace(
            full_stage.provenance,
            effective_identity={
                **dict(full_stage.provenance.effective_identity),
                "mode": "regex_legal",
            },
        ),
    )
    with pytest.raises(
        SemanticReassessmentError,
        match="requested/effective mode identity mismatched",
    ):
        validate_semantic_frontend_stage_v2(
            mismatched_identity,
            target.source_text,
        )

    regex_payload, _ = _projection_payload(
        target,
        "spacy_regex_legal",
    )
    wrong_projection = _record(
        target,
        producer_id="spacy_full_model",
        payload=regex_payload,
    )
    symai_payload, _ = _projection_payload(target, "symai")
    symai_stage = _record(
        target,
        producer_id="symai",
        payload=symai_payload,
    )
    upstream_coordinate = SemanticCalibrationCoordinateV2(
        case_id=target.case_id,
        producer_id="symai",
        stages=(wrong_projection, symai_stage),
    )
    with pytest.raises(
        SemanticReassessmentError,
        match="projection producer differs from its exact mode identity",
    ):
        evaluate_semantic_calibration_coordinate_v2(
            target,
            upstream_coordinate,
        )


def test_later_vacuous_symai_failure_is_terminal_and_never_falls_back() -> None:
    target = _target()
    compiler_payload, _ = _projection_payload(target, "compiler")
    coordinate = SemanticCalibrationCoordinateV2(
        case_id=target.case_id,
        producer_id="symai",
        stages=(
            _record(
                target,
                producer_id="compiler",
                payload=compiler_payload,
            ),
            _symai_failure(
                target,
                "semantic_projection_incomplete",
            ),
        ),
    )

    receipt = evaluate_semantic_calibration_coordinate_v2(
        target,
        coordinate,
    )
    assert (
        validate_semantic_frontend_stage_v2(
            coordinate.stages[-1],
            target.source_text,
        )
        is None
    )

    assert receipt["terminal_stage"] == "symai"
    assert receipt["terminal_stage_failed"] is True
    assert receipt["fallback_to_earlier_producer"] is False
    assert receipt["status"] == "semantic_projection_incomplete"
    assert receipt["quality_millionths"] == 0
    assert receipt["observed_semantics"] is None


def test_unretained_oversized_symai_failure_keeps_cid_and_byte_receipt() -> None:
    target = _target()
    oversized_raw = "x" * 4_097
    raw_cid = cid_for_bytes(oversized_raw.encode("utf-8"))
    body = {
        "schema": SEMANTIC_FAILURE_SCHEMA_V2,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "stage": "symai",
        "failure_subcode": "semantic_projection_incomplete",
        "source_cid": target.source_cid,
        "proof_context_cid": None,
        "evidence": {
            "raw_output_cid": raw_cid,
            "raw_output_bytes": 4_097,
        },
    }
    payload = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark.symai-evidence.v2"
        ),
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "raw_output": None,
        "raw_output_cid": raw_cid,
        "raw_output_bytes": 4_097,
        "raw_output_retained_exactly": False,
        "semantic_projection": None,
        "semantic_failure": {
            **body,
            "receipt_cid": cid_for_dag_json(body),
        },
    }
    coordinate = SemanticCalibrationCoordinateV2(
        case_id=target.case_id,
        producer_id="symai",
        stages=(
            _record(
                target,
                producer_id="symai",
                payload=payload,
                status=StageStatus.FAILED,
                failure_code=(
                    FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE
                ),
                failure_detail="oversized synthetic response",
            ),
        ),
    )

    receipt = evaluate_semantic_calibration_coordinate_v2(
        target,
        coordinate,
    )

    assert receipt["terminal_stage"] == "symai"
    assert receipt["status"] == "semantic_projection_incomplete"
    assert receipt["quality_millionths"] == 0


def test_validation_errors_precede_ambiguity() -> None:
    target = _target()
    payload, _projection = _projection_payload(
        target,
        "symai",
        ambiguity_flags=("multiple_readings",),
        validation_errors=("invalid_predicate",),
    )
    coordinate = SemanticCalibrationCoordinateV2(
        case_id=target.case_id,
        producer_id="symai",
        stages=(
            _record(
                target,
                producer_id="symai",
                payload=payload,
            ),
        ),
    )

    receipt = evaluate_semantic_calibration_coordinate_v2(
        target,
        coordinate,
    )

    assert receipt["status"] == "semantic_validation_failed"
    assert receipt["quality_millionths"] == 0
    assert receipt["validation_error_precedence_applied"] is True
    assert receipt["field_matches"]["class"] is False


def test_schema_incompatible_is_null_but_complete_all_wrong_is_zero() -> None:
    targets = tuple(
        _target(case_id=f"synthetic-{index:03d}")
        for index in range(20)
    )
    producers = (
        "compiler",
        "spacy_full_model",
        "spacy_regex_legal",
        "spacy_blank_model",
        "symai",
    )
    undersized_population = evaluate_semantic_calibration_v2(
        targets=(targets[0],),
        coordinates=tuple(
            _coordinate(targets[0], producer_id, correct=True)
            for producer_id in producers
        ),
    )
    assert (
        undersized_population["status"]
        == "semantic_schema_incompatible"
    )
    assert undersized_population["scope"]["expected_case_count"] == 20
    assert undersized_population["scope"]["observed_case_count"] == 1
    assert (
        undersized_population["scope"]["expected_coordinate_count"]
        == 100
    )
    assert (
        undersized_population["coverage"]["case_population_complete"]
        is False
    )
    assert (
        undersized_population["quality"]["semantic_quality_rate"]
        is None
    )
    assert (
        undersized_population["absolute_quality_gate"]["passed"]
        is False
    )

    missing_report = evaluate_semantic_calibration_v2(
        targets=targets,
        coordinates=tuple(
            _coordinate(target, producer_id, correct=False)
            for target in targets
            for producer_id in producers[:-1]
        ),
    )
    assert missing_report["status"] == "semantic_schema_incompatible"
    assert missing_report["quality"]["semantic_quality_rate"] is None
    assert missing_report["quality"]["schema_incompatible_is_null"] is True
    assert missing_report["shortlist"]["selected_variant_ids"] == []
    assert missing_report["holdout_authorized"] is False

    all_wrong_coordinates = tuple(
        _coordinate(target, producer_id, correct=False)
        for target in targets
        for producer_id in producers
    )
    all_wrong = evaluate_semantic_calibration_v2(
        targets=targets,
        coordinates=all_wrong_coordinates,
    )
    assert all_wrong["status"] == "synthetic_or_unvalidated_graph"
    assert all_wrong["quality"]["semantic_quality_rate"] is None
    assert (
        all_wrong["quality"]["diagnostic_coordinate_quality_rate"]
        == 0.0
    )
    assert all_wrong["quality"]["all_wrong_is_measured_zero"] is False
    assert all_wrong["absolute_quality_gate"]["passed"] is False
    assert all_wrong["relative_selection"]["applied"] is False
    assert all_wrong["shortlist"]["selected_variant_ids"] == []
    assert all_wrong["holdout_authorized"] is False

    # A caller-constructed binding is descriptive data, never an authority
    # token for the public synthetic evaluator.
    forged_bound = tuple(
        SemanticCalibrationCoordinateV2(
            case_id=coordinate.case_id,
            producer_id=coordinate.producer_id,
            stages=coordinate.stages,
            graph_binding=SemanticCalibrationGraphBindingV2(
                plan_cid=cid_for_dag_json(
                    {"synthetic_plan": True}
                ),
                plan_sha256="c" * 64,
                case_result_cid=cid_for_dag_json(
                    {"synthetic_case_result": True}
                ),
                case_result_sha256="d" * 64,
                run_id=_RUN_ID,
                variant_id="A0",
                split="pilot",
                cache_mode="cold",
                environment_sha256=_ENVIRONMENT_SHA256,
                case_manifest_sha256=_MANIFEST_SHA256,
                producer_registry_cid=(
                    SEMANTIC_PRODUCER_REGISTRY_V2_CID
                ),
                calibration_route_manifest_cid=(
                    SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID
                ),
                calibration_metric_spec_cid=(
                    SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID
                ),
                reviewed_target_source_cid=(
                    SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID
                ),
                reviewed_target_manifest_cid=cid_for_dag_json(
                    {"synthetic": True}
                ),
                proof_stages_suppressed=True,
            ),
        )
        for coordinate in all_wrong_coordinates
    )
    forged_report = evaluate_semantic_calibration_v2(
        targets=targets,
        coordinates=forged_bound,
    )
    assert forged_report["status"] == "synthetic_or_unvalidated_graph"
    assert (
        forged_report["coverage"][
            "validated_ablation_graph_coverage_complete"
        ]
        is False
    )
    assert forged_report["quality"]["semantic_quality_rate"] is None
    assert forged_report["absolute_quality_gate"]["passed"] is False
    assert forged_report["relative_selection"]["selected_producer_ids"] == []
