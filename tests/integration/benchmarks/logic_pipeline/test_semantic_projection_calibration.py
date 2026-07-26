"""End-to-end synthetic calibration of every revision-2 producer identity.

The calibration population is injected in memory.  This file intentionally
does not import a corpus loader or reference any holdout path.
"""

from __future__ import annotations

import hashlib

from benchmarks.logic_pipeline.content_addressing import (
    cid_for_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL_SHA256,
    SEMANTIC_PRODUCER_IDS_V2,
    SEMANTIC_PROTOCOL_V2_CID,
    STAGE_PROVENANCE_SCHEMA,
    CacheMode,
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
    SemanticCalibrationTargetV2,
    evaluate_semantic_calibration_v2,
)


def _input_digest(text: str) -> str:
    return hashlib.sha256(
        canonical_json({"text": text}).encode("utf-8")
    ).hexdigest()


def _stage_name(producer_id: str) -> StageName:
    if producer_id == "compiler":
        return StageName.COMPILER
    if producer_id == "symai":
        return StageName.SYMAI
    return StageName.SPACY


def _coordinate(
    target: SemanticCalibrationTargetV2,
    producer_id: str,
    *,
    correct: bool,
) -> SemanticCalibrationCoordinateV2:
    stage = _stage_name(producer_id)
    logic = target.logic_family if correct else "fol"
    semantic_target = target.target if correct else "unrelated_action"
    semantic_class = target.semantic_class if correct else "disproved"
    predicates = (
        target.predicates if correct else ("unrelated_action",)
    )
    entities = target.entities if correct else ("unrelated_entity",)
    completeness = {
        "logic_family": True,
        "target": True,
        "class": True,
        "predicates": True,
        "entities": True,
    }
    modal_ir = {
        "formulas": [
            {
                "operator": {"family": logic},
                "predicate": {
                    "name": semantic_target,
                    "arguments": list(entities),
                },
            }
        ]
    }
    response = {
        "logic_family": logic,
        "target": semantic_target,
        "class": semantic_class,
        "predicates": list(predicates),
        "entities": list(entities),
        "completeness": completeness,
        "ambiguity_flags": [],
        "confidence_millionths": 800_000,
        "validation_errors": [],
    }
    evidence_cid = (
        cid_for_dag_json(response)
        if stage is StageName.SYMAI
        else cid_for_dag_json(modal_ir)
    )
    projection = SemanticProjection.create(
        producer_id=producer_id,
        source_text=target.source_text,
        logic_family=logic,
        target=semantic_target,
        semantic_class=semantic_class,
        predicates=predicates,
        entities=entities,
        completeness=completeness,
        confidence_millionths=800_000,
        evidence_cid=evidence_cid,
    )
    if stage is StageName.COMPILER:
        payload: dict[str, object] = {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark.compiler-output.v2"
            ),
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "source_cid": target.source_cid,
            "modal_ir": modal_ir,
            "modal_ir_cid": evidence_cid,
            "retained_modal_ir_cid": evidence_cid,
            "semantic_projection": projection.to_dict(),
        }
    elif stage is StageName.SPACY:
        payload = {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark.spacy-evidence.v2"
            ),
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "document": {"source_cid": target.source_cid},
            "modal_ir": modal_ir,
            "modal_ir_cid": evidence_cid,
            "semantic_projection": projection.to_dict(),
        }
    else:
        raw_output = canonical_json(response)
        payload = {
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
        }
    identity: dict[str, object] = {
        "graph_invoked": True,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "source_cid": target.source_cid,
        "proof_context_cid": None,
    }
    if stage is StageName.SPACY:
        identity["mode"] = {
            "spacy_full_model": "full_model",
            "spacy_regex_legal": "regex_legal",
            "spacy_blank_model": "blank_model",
        }[producer_id]
    provenance = StageProvenance(
        schema=STAGE_PROVENANCE_SCHEMA,
        adapter_id=f"{stage.value}-adapter",
        adapter_version="2",
        source=("synthetic_calibration",),
        requested_identity=identity,
        effective_identity=identity,
        input_sha256=_input_digest(target.source_text),
        environment_sha256="e" * 64,
    )
    record = StageRecord.create(
        protocol_sha256=DEFAULT_PROTOCOL_SHA256,
        run_id="synthetic-calibration-v2",
        case_id=target.case_id,
        case_manifest_sha256="a" * 64,
        variant_id="A0",
        split=Split.PILOT,
        cache_mode=CacheMode.COLD,
        stage=stage,
        adapter_version="2",
        status=StageStatus.SUCCESS,
        provenance=provenance,
        telemetry=TelemetryRecord(),
        data=payload,
    )
    return SemanticCalibrationCoordinateV2(
        case_id=target.case_id,
        producer_id=producer_id,
        stages=(record,),
    )


def test_synthetic_grid_proves_coverage_but_cannot_open_gate() -> None:
    targets = tuple(
        SemanticCalibrationTargetV2(
            case_id=f"synthetic-calibration-{index:03d}",
            source_text=f"An agency must publish notice {index}.",
            logic_family="deontic",
            target="publish_notice",
            semantic_class="proved",
            predicates=("publish_notice",),
            entities=("agency", f"notice_{index}"),
        )
        for index in range(20)
    )
    coordinates = tuple(
        _coordinate(
            target,
            producer_id,
            correct=producer_id == "compiler",
        )
        for target in targets
        for producer_id in SEMANTIC_PRODUCER_IDS_V2
    )

    report = evaluate_semantic_calibration_v2(
        targets=targets,
        coordinates=coordinates,
    )

    assert report["status"] == "synthetic_or_unvalidated_graph"
    assert report["scope"]["expected_coordinate_count"] == 100
    assert report["scope"]["observed_coordinate_count"] == 100
    assert report["coverage"]["coordinate_coverage_complete"] is True
    assert report["coverage"]["field_coverage_complete"] is True
    assert report["quality"]["semantic_quality_rate"] is None
    assert report["quality"]["diagnostic_coordinate_quality_rate"] == 0.2
    assert report["absolute_quality_gate"]["passed"] is False
    assert report["relative_selection"]["applied"] is False
    assert report["relative_selection"]["selected_producer_ids"] == []
    assert report["shortlist"]["selected_variant_ids"] == []
    assert report["holdout_authorized"] is False
    assert report["production_promotion_authorized"] is False
    assert str(report["artifact_cid"]).startswith("b")
    for producer_id in SEMANTIC_PRODUCER_IDS_V2:
        assert all(
            count == 20
            for count in report["coverage"]["field_coordinate_counts"][
                producer_id
            ].values()
        )
