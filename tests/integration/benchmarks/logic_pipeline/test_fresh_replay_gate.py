"""Source-safe focused tests for complete-evidence HSSL-G238 replay.

The runtime pairs are synthesized in temporary directories.  These tests do
not open a benchmark fixture, corpus, manifest, or holdout.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from benchmarks.logic_pipeline import contracts
from benchmarks.logic_pipeline.ablation import (
    AblationCase,
    build_semantic_ablation_plan,
)
from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.logic_pipeline.namespace_provenance import (
    G240ReplayNamespaceReceiptV2,
    G240RuntimeNamespaceReceiptV2,
    build_g240_namespace_policy_v2,
    validate_g240_replay_namespace_receipt_v2,
)
from benchmarks.logic_pipeline.replay_gate import (
    G238DetachedReplayReceiptV2,
    G238ReplaySourceIndexV2,
    G238ReplaySourceRecordV2,
    G238SemanticObservationV2,
    FreshReplayGateError,
    build_g238_detached_replay_gate_v2,
    build_g238_replay_comparison_v2,
    validate_g238_detached_replay_gate_v2,
    validate_g238_replay_comparison_v2,
    validate_g238_semantic_observation_v2,
)
from benchmarks.logic_pipeline.resource_statistics import (
    IndependentComponentResourceV2,
    IndependentResourceReceiptV2,
    build_independent_resource_receipt_v2,
)
import tests.integration.benchmarks.logic_pipeline.test_revised_pilot_positive_gates as pilot
import tests.integration.benchmarks.logic_pipeline.test_reviewed_control_safety as control


COMMIT = "a" * 40


def _cid(label: str) -> str:
    return cid_for_dag_json({"synthetic": label})


def _component(
    *,
    wall_time_ms: float = 10.0,
    missing_wall_time: bool = False,
) -> IndependentComponentResourceV2:
    return IndependentComponentResourceV2(
        component_id="pipeline",
        wall_time_ms=None if missing_wall_time else wall_time_ms,
        peak_memory_bytes=1_000_000,
        model_calls=0,
        retries=0,
        solver_processes=0,
        accelerator_minutes=0.0,
        queue_delay_ms=1.0,
        released=True,
        process_group_reaped=True,
        missing_reasons=(
            {"wall_time_ms": "synthetic meter omitted wall time"}
            if missing_wall_time
            else {}
        ),
    )


def _resource(
    evidence,
    label: str,
    *,
    wall_time_ms: float = 10.0,
    missing_wall_time: bool = False,
) -> IndependentResourceReceiptV2:
    return build_independent_resource_receipt_v2(
        evidence,
        (
            _component(
                wall_time_ms=wall_time_ms,
                missing_wall_time=missing_wall_time,
            ),
        ),
        producer_identity_cid=_cid(f"{label}-producer"),
        meter_identity_cid=_cid(f"{label}-meter"),
        validator_identity_cid=_cid(f"{label}-validator"),
    )


def _failed_runtime(
    root: Path,
    *,
    run_id: str,
    case_id: str,
    compiler_note: str = "synthetic-g238",
):
    previous = pilot.COMPLETE_RUN_ID
    pilot.COMPLETE_RUN_ID = run_id
    try:
        return pilot._coordinate_evidence(
            root,
            case_id=case_id,
            source_text=pilot.SOURCE_TEXT,
            proof_context=pilot.PROOF_CONTEXT,
            split=contracts.Split.PILOT,
            cache_mode=contracts.CacheMode.COLD,
            variant_ids=("A2",),
            compiler_note=compiler_note,
        )[0]
    finally:
        pilot.COMPLETE_RUN_ID = previous


def _verified_runtime(root: Path, *, run_id: str):
    previous = control.RUN_ID
    control.RUN_ID = run_id
    try:
        return control._coordinate_evidence(
            root,
            cache_mode=contracts.CacheMode.COLD,
            variant_ids=("A0",),
            kernel_returncode=0,
            namespace=run_id,
        )[0]
    finally:
        control.RUN_ID = previous


@pytest.fixture(scope="module")
def g238_sources(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("synthetic-g238")
    source_runtimes = (
        _verified_runtime(root / "source-success", run_id="source-run"),
        _failed_runtime(
            root / "source-failure-1",
            run_id="source-run",
            case_id="g238-failure-one",
        ),
        _failed_runtime(
            root / "source-failure-2",
            run_id="source-run",
            case_id="g238-failure-two",
        ),
    )
    replay_runtimes = (
        _verified_runtime(root / "replay-success", run_id="replay-0"),
        _failed_runtime(
            root / "replay-failure-1",
            run_id="replay-1",
            case_id="g238-failure-one",
        ),
        _failed_runtime(
            root / "replay-failure-2",
            run_id="replay-2",
            case_id="g238-failure-two",
        ),
    )
    records = tuple(
        G238ReplaySourceRecordV2.create(
            runtime_evidence=evidence,
            semantic_observation=G238SemanticObservationV2.create(
                evidence
            ),
            resource_receipt=_resource(
                evidence,
                f"source-{ordinal}",
            ),
        )
        for ordinal, evidence in enumerate(source_runtimes)
    )
    index = G238ReplaySourceIndexV2.create(
        source_run_id="source-run",
        source_commit=COMMIT,
        recursive_gitlinks_cid=_cid("gitlinks"),
        environment_cid=_cid("environment"),
        route_manifest_cid=_cid("routes"),
        case_index_cid=_cid("cases"),
        run_plan_cid=_cid("run-plan"),
        source_worktree_cid=_cid("source-worktree"),
        source_executor_authority_cid=_cid("source-executor"),
        records=records,
    )
    replay_by_case = {
        record.case_cid: replay
        for record, replay in zip(records, replay_runtimes)
    }
    return {
        "root": root,
        "index": index,
        "replay_by_case": replay_by_case,
    }


def _receipt(
    index: G238ReplaySourceIndexV2,
    record: G238ReplaySourceRecordV2,
    ordinal: int,
    replay_runtime,
    *,
    resource: IndependentResourceReceiptV2 | None = None,
    semantic: G238SemanticObservationV2 | None = None,
    include_resource: bool = True,
    detached: bool = True,
    attached: bool = False,
    holdout_accessed: bool = False,
) -> G238DetachedReplayReceiptV2:
    replay_resource = (
        resource
        if resource is not None
        else (
            _resource(replay_runtime, f"replay-{ordinal}")
            if include_resource
            else None
        )
    )
    return G238DetachedReplayReceiptV2.create(
        source_index=index,
        source_record=record,
        replay_run_id=replay_runtime.case_result.run_id,
        replay_worktree_cid=_cid(f"replay-worktree-{ordinal}"),
        source_namespace_receipt_cid=_cid(
            f"source-namespace-receipt-{ordinal}"
        ),
        source_process_namespace_cid=_cid(
            f"source-process-{ordinal}"
        ),
        source_state_namespace_cid=_cid(
            f"source-state-{ordinal}"
        ),
        source_cache_namespace_cid=_cid(
            f"source-cache-{ordinal}"
        ),
        replay_process_namespace_cid=_cid(
            f"replay-process-{ordinal}"
        ),
        replay_state_namespace_cid=_cid(f"replay-state-{ordinal}"),
        replay_cache_namespace_cid=_cid(f"replay-cache-{ordinal}"),
        replay_executor_authority_cid=_cid("replay-executor"),
        replay_validator_authority_cid=_cid("replay-validator"),
        replay_runtime_evidence=replay_runtime,
        replay_semantic_observation=(
            semantic
            if semantic is not None
            else G238SemanticObservationV2.create(replay_runtime)
        ),
        replay_resource_receipt=replay_resource,
        detached=detached,
        attached=attached,
        auto_merge=False,
        holdout_accessed=holdout_accessed,
    )


def _complete_receipts(
    index: G238ReplaySourceIndexV2,
    replay_by_case: dict[str, object],
) -> tuple[G238DetachedReplayReceiptV2, ...]:
    return tuple(
        _receipt(
            index,
            record,
            ordinal,
            replay_by_case[record.case_cid],
        )
        for ordinal, record in enumerate(index.required_records)
    )


def _rebased_receipt(
    receipt: G238DetachedReplayReceiptV2,
    **changes: object,
) -> G238DetachedReplayReceiptV2:
    payload = receipt.to_dict()
    payload.update(changes)
    body = {
        key: value
        for key, value in payload.items()
        if key != "receipt_cid"
    }
    payload["receipt_cid"] = cid_for_dag_json(body)
    return G238DetachedReplayReceiptV2.from_dict(payload)


def test_receipt_only_gate_cannot_claim_operational_replay(
    g238_sources,
) -> None:
    index = g238_sources["index"]
    receipts = _complete_receipts(
        index,
        g238_sources["replay_by_case"],
    )

    gate = build_g238_detached_replay_gate_v2(
        index,
        receipts,
        validator_authority_cid=_cid("replay-validator"),
    )

    assert gate["passed"] is False
    assert gate["status"] == "incomplete"
    assert gate["source_success_count"] == 1
    assert gate["source_failure_count"] == 2
    # Every success plus one lexicographically selected A2 failure.
    assert gate["required_replay_count"] == 2
    assert gate["failure_codes"] == [
        "missing_operational_replay_source"
    ]
    assert len(gate["validated_comparison_receipt_cids"]) == 2
    assert gate["validated_namespace_receipt_cids"] == []
    assert gate["validated_orchestration_receipt_cids"] == []
    assert all(
        receipt.replay_runtime_evidence.receipt_cid
        != index.required_records[position].runtime_evidence_cid
        for position, receipt in enumerate(receipts)
    )
    assert (
        validate_g238_detached_replay_gate_v2(
            gate,
            G238ReplaySourceIndexV2.from_dict(index.to_dict()),
            [
                G238DetachedReplayReceiptV2.from_dict(
                    receipt.to_dict()
                )
                for receipt in receipts
            ],
            validator_authority_cid=_cid("replay-validator"),
        )
        == gate["receipt_cid"]
    )


def test_g240_recomputes_fresh_replay_namespace_from_full_runtime(
    g238_sources,
) -> None:
    index = g238_sources["index"]
    record = next(
        item
        for item in index.records
        if item.variant_id == "A0"
    )
    source_runtime = record.runtime_evidence
    replay_runtime = g238_sources["replay_by_case"][record.case_cid]
    source_result = source_runtime.case_result
    plan = build_semantic_ablation_plan(
        source_result.run_id,
        (
            AblationCase.create(
                source_result.case_id,
                {"text": source_runtime.source_text},
                split=source_result.split,
            ),
        ),
        case_manifest_sha256=source_result.case_manifest_sha256,
        split=source_result.split,
        seed=83,
        variant_ids=(source_result.variant_id,),
        cache_modes=(source_result.cache_mode,),
        environment_sha256=(
            source_result.stages[0].provenance.environment_sha256
        ),
    )
    policy = build_g240_namespace_policy_v2(
        (plan,),
        source_commit_cid=index.source_commit_cid,
        recursive_gitlinks_cid=index.recursive_gitlinks_cid,
        environment_cid=index.environment_cid,
        runtime_orchestration_policy_cid=_cid(
            "g240-source-executor-contract"
        ),
        namespace_authority_cid=_cid("g240-policy-authority"),
    )
    source_receipt = G240RuntimeNamespaceReceiptV2.create(
        policy=policy,
        plan=plan,
        job=plan.jobs[0],
        evidence=source_runtime,
        executor_identity_cid=_cid("g240-source-executor"),
        observer_identity_cid=_cid("g240-source-observer"),
        process_group_started=True,
        process_group_reaped=True,
        active_process_count_after_reap=0,
        state_namespace_created_exclusive=True,
        state_namespace_finalized=True,
        output_namespace_created_exclusive=True,
        output_namespace_finalized=True,
        cache_namespaces_mounted=True,
    )
    replay_receipt = G240ReplayNamespaceReceiptV2.create(
        source_policy=policy,
        source_receipt=source_receipt,
        replay_run_id=replay_runtime.case_result.run_id,
        replay_worktree_cid=_cid("g240-replay-worktree"),
        replay_runtime_evidence=replay_runtime,
        replay_executor_identity_cid=_cid("g240-replay-executor"),
        replay_observer_identity_cid=_cid("g240-replay-observer"),
        process_group_started=True,
        process_group_reaped=True,
        active_process_count_after_reap=0,
        state_namespace_created_exclusive=True,
        state_namespace_finalized=True,
        output_namespace_created_exclusive=True,
        output_namespace_finalized=True,
        cache_namespaces_mounted=True,
    )

    restored = validate_g240_replay_namespace_receipt_v2(
        replay_receipt.to_dict(),
        source_policy=policy,
        source_receipt=source_receipt,
        source_runtime_evidence=source_runtime,
        replay_runtime_evidence=replay_runtime,
    )

    assert restored.receipt_cid == replay_receipt.receipt_cid
    assert (
        restored.replay_process_namespace_cid
        != source_receipt.process_namespace_cid
    )
    assert (
        restored.replay_state_namespace_cid
        != source_receipt.state_namespace_cid
    )
    assert not (
        set(restored.replay_cache_namespace_cids.values())
        & set(source_receipt.cache_namespace_cids.values())
    )


def test_semantic_observation_and_comparison_are_runtime_recomputed(
    g238_sources,
) -> None:
    index = g238_sources["index"]
    record = index.required_records[0]
    replay = g238_sources["replay_by_case"][record.case_cid]
    semantic = G238SemanticObservationV2.create(replay)
    resource = _resource(replay, "direct-comparison")
    comparison = build_g238_replay_comparison_v2(
        record,
        replay,
        semantic,
        resource,
    )

    assert comparison["passed"] is True
    assert comparison["semantic_equal"] is True
    assert comparison["kernel_equal"] is True
    assert comparison["status_equal"] is True
    assert comparison["resource_identity_equal"] is True
    assert (
        validate_g238_semantic_observation_v2(semantic, replay)
        == semantic
    )
    assert (
        validate_g238_replay_comparison_v2(
            comparison,
            record,
            replay,
            semantic,
            resource,
        )
        == comparison["comparison_receipt_cid"]
    )


def test_copied_source_observation_is_not_replay_evidence(
    g238_sources,
) -> None:
    index = g238_sources["index"]
    record = index.required_records[0]
    replay = g238_sources["replay_by_case"][record.case_cid]

    with pytest.raises(
        FreshReplayGateError,
        match="did not runtime-recompute",
    ):
        _receipt(
            index,
            record,
            50,
            replay,
            semantic=record.semantic_observation,
        )


def test_semantic_drift_is_detected_from_complete_runtime(
    g238_sources,
) -> None:
    index = g238_sources["index"]
    record = next(
        item
        for item in index.required_records
        if item.variant_id == "A2"
    )
    drift = _failed_runtime(
        g238_sources["root"] / "semantic-drift",
        run_id="semantic-drift-run",
        case_id=record.runtime_evidence.case_result.case_id,
        compiler_note="semantic output deliberately changed",
    )
    receipt = _receipt(index, record, 60, drift)

    gate = build_g238_detached_replay_gate_v2(
        index,
        [receipt],
        validator_authority_cid=_cid("replay-validator"),
    )

    assert "semantic_identity_mismatch" in gate["failure_codes"]


@pytest.mark.parametrize(
    ("wall_time_ms", "missing", "expected_code"),
    (
        (
            100.0,
            False,
            "resource_replay_measurement_out_of_tolerance",
        ),
        (
            10.0,
            True,
            "resource_replay_measurement_missing",
        ),
    ),
)
def test_resource_measurements_use_frozen_tolerances_and_missingness(
    g238_sources,
    wall_time_ms: float,
    missing: bool,
    expected_code: str,
) -> None:
    index = g238_sources["index"]
    receipts = list(
        _complete_receipts(index, g238_sources["replay_by_case"])
    )
    record = index.required_records[0]
    replay = g238_sources["replay_by_case"][record.case_cid]
    resource = _resource(
        replay,
        f"resource-failure-{expected_code}",
        wall_time_ms=wall_time_ms,
        missing_wall_time=missing,
    )
    receipts[0] = _receipt(
        index,
        record,
        0,
        replay,
        resource=resource,
    )

    gate = build_g238_detached_replay_gate_v2(
        index,
        receipts,
        validator_authority_cid=_cid("replay-validator"),
    )

    assert gate["passed"] is False
    assert expected_code in gate["failure_codes"]


def test_partial_isolation_staleness_and_holdout_fail_closed(
    g238_sources,
) -> None:
    index = g238_sources["index"]
    records = index.required_records
    replay = g238_sources["replay_by_case"][records[0].case_cid]
    partial = _receipt(
        index,
        records[0],
        0,
        replay,
        include_resource=False,
    )
    other = _receipt(
        index,
        records[1],
        1,
        g238_sources["replay_by_case"][records[1].case_cid],
    )
    gate = build_g238_detached_replay_gate_v2(
        index,
        (partial, other),
        validator_authority_cid=_cid("replay-validator"),
    )
    assert "partial_replay_evidence" in gate["failure_codes"]

    complete = list(
        _complete_receipts(index, g238_sources["replay_by_case"])
    )
    complete[0] = _rebased_receipt(
        complete[0],
        environment_cid=_cid("stale-environment"),
        detached=False,
        attached=True,
        holdout_accessed=True,
    )
    gate = build_g238_detached_replay_gate_v2(
        index,
        complete,
        validator_authority_cid=_cid("replay-validator"),
    )
    assert "stale_source_binding" in gate["failure_codes"]
    assert "replay_not_detached" in gate["failure_codes"]
    assert "replay_accessed_holdout" in gate["failure_codes"]


def test_rebased_comparison_and_outer_cids_do_not_bypass_source_replay(
    g238_sources,
) -> None:
    index = g238_sources["index"]
    receipts = list(
        _complete_receipts(index, g238_sources["replay_by_case"])
    )
    payload = receipts[0].to_dict()
    comparison = payload["comparison"]
    assert isinstance(comparison, dict)
    comparison["semantic_equal"] = False
    comparison_body = {
        key: value
        for key, value in comparison.items()
        if key != "comparison_receipt_cid"
    }
    comparison["comparison_receipt_cid"] = cid_for_dag_json(
        comparison_body
    )
    outer_body = {
        key: value
        for key, value in payload.items()
        if key != "receipt_cid"
    }
    payload["receipt_cid"] = cid_for_dag_json(outer_body)
    receipts[0] = G238DetachedReplayReceiptV2.from_dict(payload)

    gate = build_g238_detached_replay_gate_v2(
        index,
        receipts,
        validator_authority_cid=_cid("replay-validator"),
    )

    assert "replay_comparison_not_source_recomputed" in (
        gate["failure_codes"]
    )


def test_missing_duplicate_unexpected_shared_and_cid_tampering(
    g238_sources,
) -> None:
    index = g238_sources["index"]
    complete = list(
        _complete_receipts(index, g238_sources["replay_by_case"])
    )
    missing = build_g238_detached_replay_gate_v2(
        index,
        complete[:-1],
        validator_authority_cid=_cid("replay-validator"),
    )
    assert "missing_required_replay" in missing["failure_codes"]

    duplicate = build_g238_detached_replay_gate_v2(
        index,
        [*complete, complete[0]],
        validator_authority_cid=_cid("replay-validator"),
    )
    assert "duplicate_replay_target" in duplicate["failure_codes"]

    complete[1] = _rebased_receipt(
        complete[1],
        replay_worktree_cid=complete[0].replay_worktree_cid,
        replay_process_namespace_cid=(
            complete[0].replay_process_namespace_cid
        ),
    )
    shared = build_g238_detached_replay_gate_v2(
        index,
        complete,
        validator_authority_cid=_cid("replay-validator"),
    )
    assert "shared_replay_worktree_cid" in shared["failure_codes"]
    assert "shared_replay_process_namespace_cid" in (
        shared["failure_codes"]
    )

    tampered = complete[0].to_dict()
    tampered["receipt_cid"] = _cid("forged")
    with pytest.raises(FreshReplayGateError, match="CID changed"):
        G238DetachedReplayReceiptV2.from_dict(tampered)


def test_source_record_rejects_derived_field_tampering(
    g238_sources,
) -> None:
    original = g238_sources["index"].records[0]
    with pytest.raises(
        FreshReplayGateError,
        match="source coordinate differs",
    ):
        replace(original, split="development")
    with pytest.raises(
        FreshReplayGateError,
        match="derived identity changed",
    ):
        replace(
            original,
            semantic_identity_cid=_cid("caller-copied-or-changed"),
        )
