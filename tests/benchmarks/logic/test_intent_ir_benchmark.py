"""Deterministic paired formalization benchmark contract tests."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.intent_ir.evaluation.benchmark import (
    IntentBenchmarkArm,
    IntentBenchmarkCost,
    IntentBenchmarkError,
    IntentBenchmarkExample,
    IntentBenchmarkIntegrityError,
    IntentBenchmarkObservation,
    IntentFormalizationBenchmark,
    run_intent_formalization_benchmark,
)
from ipfs_datasets_py.logic.intent_ir.evaluation.splits import (
    TEST_PARTITION,
    TRAIN_PARTITION,
    IntentSplitExample,
    IntentSplitManifest,
)
from ipfs_datasets_py.logic.intent_ir.formalize.compiler import (
    INTENT_MODAL_VIEW_ID,
    IntentFormalizationCompiler,
)
from ipfs_datasets_py.logic.intent_ir.formalize.obligations import (
    IntentProofDisposition,
    IntentProofExecution,
    IntentProofObligations,
    IntentProofOutcome,
)
from ipfs_datasets_py.logic.intent_ir.schema import (
    ControlEdgeKind,
    IntentAction,
    IntentControlEdge,
    IntentIRDocument,
    IntentKind,
    IntentModality,
    IntentStatement,
    SourceRef,
    StatementKind,
)


def _document(
    sample_id: str = "intent:benchmark:test",
    *,
    source_id: str = "held-out-source",
    content: str = "a",
) -> IntentIRDocument:
    document = IntentIRDocument(
        document_id=sample_id,
        title="Publish and archive a result",
        intent_kind=IntentKind.PROCEDURE,
        sources=(
            SourceRef(
                ref_id=f"source:{source_id}",
                source_uri=f"urn:test:{source_id}",
                source_id=source_id,
                source_revision="v1",
                content_sha256=content * 64,
            ),
        ),
        statements=(
            IntentStatement(
                statement_id="statement:goal",
                kind=StatementKind.GOAL,
                modality=IntentModality.INTENDED,
                normalized_text="Publish the result",
                predicate="publish",
                arguments=("result",),
                source_ref_ids=(f"source:{source_id}",),
                confidence=1.0,
            ),
        ),
        actions=(
            IntentAction(
                action_id="action:publish",
                actor="agent",
                verb="publish",
                object_refs=("result",),
                source_ref_ids=(f"source:{source_id}",),
            ),
            IntentAction(
                action_id="action:archive",
                actor="agent",
                verb="archive",
                object_refs=("result",),
                source_ref_ids=(f"source:{source_id}",),
            ),
        ),
        control_edges=(
            IntentControlEdge(
                edge_id="edge:publish-archive",
                source_action_id="action:publish",
                target_action_id="action:archive",
                kind=ControlEdgeKind.ON_SUCCESS,
                source_ref_ids=(f"source:{source_id}",),
            ),
        ),
        entry_action_ids=("action:publish",),
        terminal_action_ids=("action:archive",),
    )
    document.validate()
    return document


def _manifest(
    document: IntentIRDocument,
    *,
    extra: tuple[tuple[IntentIRDocument, str], ...] = (),
) -> IntentSplitManifest:
    examples = (IntentSplitExample.from_sample(document),) + tuple(
        IntentSplitExample.from_sample(
            item,
            content_digests=tuple(
                source.content_sha256 for source in item.sources
            ),
            near_duplicate_signature=(),
        )
        for item, _ in extra
    )
    assignments = {document.document_id: TEST_PARTITION}
    assignments.update({item.document_id: partition for item, partition in extra})
    return IntentSplitManifest(
        examples=examples,
        assignments=assignments,
        config_digest="sha256:" + "f" * 64,
    )


def _observation(
    arm: IntentBenchmarkArm,
    document: IntentIRDocument,
    artifact,
    **changes,
) -> IntentBenchmarkObservation:
    return IntentBenchmarkObservation(
        sample_id=document.document_id,
        arm=arm,
        artifact=artifact,
        latency_ms={
            IntentBenchmarkArm.DETERMINISTIC_ONLY: 1.0,
            IntentBenchmarkArm.INTENT_FROM_SCRATCH: 2.0,
            IntentBenchmarkArm.LEGAL_ENCODER_TRANSFER: 3.0,
        }[arm],
        peak_memory_bytes={
            IntentBenchmarkArm.DETERMINISTIC_ONLY: 100,
            IntentBenchmarkArm.INTENT_FROM_SCRATCH: 200,
            IntentBenchmarkArm.LEGAL_ENCODER_TRANSFER: 300,
        }[arm],
        cost=IntentBenchmarkCost(
            input_tokens=0
            if arm is IntentBenchmarkArm.DETERMINISTIC_ONLY
            else 10,
            output_tokens=0
            if arm is IntentBenchmarkArm.DETERMINISTIC_ONLY
            else 5,
            compute_seconds=0.01,
            estimated_usd=0.0
            if arm is IntentBenchmarkArm.DETERMINISTIC_ONLY
            else 0.001,
        ),
        **changes,
    )


def test_paired_receipt_reports_every_required_quality_and_resource_metric() -> None:
    document = _document()
    compiler = IntentFormalizationCompiler()
    artifact = compiler.compile(document)
    packet = IntentProofObligations().generate(artifact)
    execution = IntentProofExecution(
        packet=packet,
        outcomes=tuple(
            IntentProofOutcome(
                obligation_id=item.obligation_id,
                disposition=IntentProofDisposition.POSITIVE,
                authoritative=True,
            )
            for item in packet.obligations
        ),
    )
    example = IntentBenchmarkExample(document=document)
    harness = IntentFormalizationBenchmark([example], _manifest(document))
    observations = [
        _observation(
            arm, document, artifact, proof_execution=execution
        )
        for arm in IntentBenchmarkArm
    ]

    report = harness.evaluate(observations)

    assert report.example_ids == (document.document_id,)
    assert report.leakage_count == 0
    assert report.authority_violation_count == 0
    assert report.promotion_eligible
    assert report.require_safe() is report
    assert set(report.metrics_by_arm) == set(IntentBenchmarkArm)
    for metrics in report.metrics_by_arm.values():
        assert metrics.grounding_accuracy == 1.0
        assert metrics.schema_validity == 1.0
        assert metrics.type_validity == 1.0
        assert metrics.view_accuracy == 1.0
        assert metrics.modality_f1 == 1.0
        assert metrics.control_f1 == 1.0
        assert metrics.proof_obligation_closure == 1.0
        assert metrics.unsupported_recall == 1.0
        assert metrics.semantic_mutation_rate == 0.0
        assert metrics.round_trip_accuracy == 1.0
        assert metrics.calibration.brier_score == 0.0
        assert metrics.false_proof_count == 0
        assert metrics.false_completion_count == 0
        assert metrics.leakage_count == 0
        assert metrics.authority_violation_count == 0
        assert metrics.mean_latency_ms > 0.0
        assert metrics.peak_memory_bytes > 0
        assert metrics.cost.compute_seconds > 0.0

    wire = report.to_dict()
    required = {
        "grounding_accuracy",
        "schema_validity",
        "type_validity",
        "view_accuracy",
        "modality_f1",
        "control_f1",
        "proof_obligation_closure",
        "unsupported_recall",
        "semantic_mutation_rate",
        "round_trip_accuracy",
        "calibration",
        "false_proof_count",
        "mean_latency_ms",
        "peak_memory_bytes",
        "cost",
    }
    assert required <= set(
        wire["metrics_by_arm"][
            IntentBenchmarkArm.DETERMINISTIC_ONLY.value
        ]
    )
    assert json.loads(report.to_json())["report_digest"] == report.digest
    assert set(report.paired_deltas) == {
        IntentBenchmarkArm.INTENT_FROM_SCRATCH,
        IntentBenchmarkArm.LEGAL_ENCODER_TRANSFER,
    }


def test_semantic_mutation_changes_modality_f1_and_round_trip() -> None:
    document = _document()
    artifact = IntentFormalizationCompiler().compile(document)
    modal = next(
        item for item in artifact.formulas if item.view_id == INTENT_MODAL_VIEW_ID
    )
    expression = dict(modal.expression)
    expression["operator"] = IntentModality.PROHIBITED.value
    mutated = replace(
        artifact,
        formulas=tuple(
            replace(item, expression=expression)
            if item.formula_id == modal.formula_id
            else item
            for item in artifact.formulas
        ),
    )
    harness = IntentFormalizationBenchmark(
        [IntentBenchmarkExample(document=document)], _manifest(document)
    )
    observations = [
        _observation(
            arm,
            document,
            mutated
            if arm is IntentBenchmarkArm.INTENT_FROM_SCRATCH
            else artifact,
        )
        for arm in IntentBenchmarkArm
    ]

    report = harness.evaluate(observations)
    candidate = report.metrics_by_arm[IntentBenchmarkArm.INTENT_FROM_SCRATCH]

    assert candidate.modality_f1 < 1.0
    assert candidate.semantic_mutation_rate == 1.0
    assert candidate.round_trip_accuracy == 0.0
    assert (
        report.paired_deltas[
            IntentBenchmarkArm.INTENT_FROM_SCRATCH
        ].semantic_mutation_rate
        == 1.0
    )


def test_cross_partition_retrieval_and_authority_claims_fail_promotion() -> None:
    document = _document()
    training_document = _document(
        "intent:benchmark:train",
        source_id="training-source",
        content="b",
    )
    manifest = _manifest(
        document, extra=((training_document, TRAIN_PARTITION),)
    )
    artifact = IntentFormalizationCompiler().compile(document)
    harness = IntentFormalizationBenchmark(
        [IntentBenchmarkExample(document=document)], manifest
    )
    observations = [
        _observation(arm, document, artifact) for arm in IntentBenchmarkArm
    ]
    observations[1] = replace(
        observations[1],
        retrieved_sample_ids=(training_document.document_id,),
        authority="proved",
        claimed_proof_ids=("obligation:model-invented",),
        claimed_completion=True,
    )

    report = harness.evaluate(observations)
    metrics = report.metrics_by_arm[IntentBenchmarkArm.INTENT_FROM_SCRATCH]

    assert report.leakage_count == 1
    assert report.authority_violation_count >= 2
    assert metrics.leakage_count == 1
    assert metrics.authority_violation_count >= 2
    assert metrics.false_proof_count == 1
    assert not metrics.promotion_safe
    assert not report.promotion_eligible
    with pytest.raises(IntentBenchmarkIntegrityError, match="not promotion-safe"):
        report.require_safe()


def test_source_family_leakage_is_rejected_before_any_runner_executes() -> None:
    document = _document()
    duplicate = _document(
        "intent:benchmark:duplicate",
        source_id="held-out-source",
        content="a",
    )
    leaked_manifest = IntentSplitManifest(
        examples=(
            IntentSplitExample.from_sample(document),
            IntentSplitExample.from_sample(duplicate),
        ),
        assignments={
            document.document_id: TEST_PARTITION,
            duplicate.document_id: TRAIN_PARTITION,
        },
        config_digest="sha256:" + "f" * 64,
    )

    with pytest.raises(IntentBenchmarkIntegrityError, match="source-family"):
        IntentFormalizationBenchmark(
            [IntentBenchmarkExample(document=document)], leaked_manifest
        )


def test_exact_paired_matrix_is_required() -> None:
    document = _document()
    artifact = IntentFormalizationCompiler().compile(document)
    harness = IntentFormalizationBenchmark(
        [IntentBenchmarkExample(document=document)], _manifest(document)
    )

    with pytest.raises(IntentBenchmarkError, match="exact paired matrix"):
        harness.evaluate(
            [
                _observation(
                    IntentBenchmarkArm.DETERMINISTIC_ONLY,
                    document,
                    artifact,
                )
            ]
        )


def test_runner_api_measures_telemetry_without_live_models() -> None:
    document = _document()
    artifact = IntentFormalizationCompiler().compile(document)
    calls: list[tuple[str, IntentBenchmarkArm]] = []

    def runner(arm):
        def invoke(example):
            calls.append((example.sample_id, arm))
            return IntentBenchmarkObservation(
                sample_id=example.sample_id,
                arm=arm,
                artifact=artifact,
            )

        return invoke

    report = run_intent_formalization_benchmark(
        [IntentBenchmarkExample(document=document)],
        _manifest(document),
        {arm: runner(arm) for arm in IntentBenchmarkArm},
    )

    assert len(calls) == len(IntentBenchmarkArm)
    assert report.promotion_eligible
    assert all(
        metrics.mean_latency_ms > 0.0
        and metrics.peak_memory_bytes > 0
        for metrics in report.metrics_by_arm.values()
    )
