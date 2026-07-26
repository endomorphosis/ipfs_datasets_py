"""Test-only operational conformance at the HSSL-G231 source boundary.

The generated case is executed by the tracked G240 module in a bounded
subprocess, persisted as a complete G211 batch, and replayed in a fresh
detached worktree for G238.  The resulting composition is deliberately marked
test-only and non-authorizing.  Production G231 must reject it.

No benchmark fixture, corpus, manifest, or holdout is loaded.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from benchmarks.logic_pipeline.causal_batch import (
    persist_causal_runtime_batch_v2,
    validate_causal_runtime_batch_v2,
)
from benchmarks.logic_pipeline.content_addressing import (
    canonical_dag_json_bytes,
    cid_for_dag_json,
)
from benchmarks.logic_pipeline.namespace_provenance import (
    G240PrivateReplayValidationSourcesV2,
    g240_cache_namespace_set_cid,
    g240_replay_namespace_request_v2,
    g240_worktree_safety_projection_cid,
)
from benchmarks.logic_pipeline.positive_gate_bundle import (
    G231_POSITIVE_GATE_BUNDLE_SCHEMA_V2,
    PositiveGateBundleError,
    _validate_g211_g240_operational_sources,
)
from benchmarks.logic_pipeline.replay import (
    run_g240_detached_replay_v2,
)
from benchmarks.logic_pipeline.replay_gate import (
    G238DetachedReplayReceiptV2,
    G238ReplaySourceIndexV2,
    G238ReplaySourceRecordV2,
    G238SemanticObservationV2,
    build_g238_detached_replay_gate_v2,
    validate_g238_detached_replay_gate_v2,
)
from benchmarks.logic_pipeline.resource_statistics import (
    IndependentComponentResourceV2,
    build_independent_resource_receipt_v2,
)
from benchmarks.logic_pipeline.source_executor import (
    G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2,
    G240SourceExecutorError,
    G240ExecutionRequestV2,
    _G240_SYNTHETIC_TEST_CAPABILITY_V2,
    validate_g240_production_execution_request_v2,
)
from benchmarks.logic_pipeline.source_orchestration import (
    build_g240_source_orchestration_evidence_set_v2,
)
from tests.integration.benchmarks.logic_pipeline.test_source_orchestration import (
    _authority,
    _execute,
)


TEST_ONLY_COMPOSITION_SCHEMA = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g231-test-only-operational-composition.v1"
)


def _identity(label: str) -> str:
    return cid_for_dag_json(
        {
            "schema": "synthetic-g231-operational-authority.v1",
            "label": label,
        }
    )


def _resource(runtime, *, producer: str, meter: str, validator: str):
    return build_independent_resource_receipt_v2(
        runtime,
        (
            IndependentComponentResourceV2(
                component_id="pipeline",
                wall_time_ms=10.0,
                peak_memory_bytes=1_000_000,
                model_calls=0,
                retries=0,
                solver_processes=0,
                accelerator_minutes=0.0,
                queue_delay_ms=1.0,
                released=True,
                process_group_reaped=True,
                missing_reasons={},
            ),
        ),
        producer_identity_cid=producer,
        meter_identity_cid=meter,
        validator_identity_cid=validator,
    )


def _test_only_composition_receipt(
    *,
    batch,
    source_result,
    replay_gate,
) -> MappingProxyType:
    """Compose already validated child receipts without authorizing G231."""

    body = {
        "schema": TEST_ONLY_COMPOSITION_SCHEMA,
        "g211_runtime_batch_receipt_cid": batch.receipt_cid,
        "g240_runtime_namespace_receipt_cid": (
            source_result.runtime_namespace_receipt.receipt_cid
        ),
        "g240_source_orchestration_receipt_cid": (
            source_result.orchestration_receipt.receipt_cid
        ),
        "g238_detached_replay_gate_receipt_cid": (
            replay_gate["receipt_cid"]
        ),
        "source_process_group_reaped": (
            source_result.process_result.process_group_reaped
        ),
        "source_process_timed_out": source_result.process_result.timed_out,
        "test_only": True,
        "complete": True,
        "passed": True,
        "production_g231_authorized": False,
        "holdout_authorized": False,
        "holdout_accessed": False,
        "production_promotion_authorized": False,
    }
    return MappingProxyType(
        {**body, "receipt_cid": cid_for_dag_json(body)}
    )


@pytest.fixture(scope="module")
def test_only_operational_chain(
    tmp_path_factory: pytest.TempPathFactory,
):
    root = tmp_path_factory.mktemp("g231-test-only-conformance")
    source_result, namespace_set, manifest, profile = _execute(root)
    source_private = source_result.validation_sources
    orchestration_set = (
        build_g240_source_orchestration_evidence_set_v2(
            namespace_set,
            (source_private,),
            validator_identity_cid=_authority(
                "orchestration-validator"
            ),
        )
    )
    output_root = root / "g211-persisted"
    batch = persist_causal_runtime_batch_v2(
        source_private.plan,
        manifest,
        profile,
        {
            source_private.job.job_id: source_result.runtime_evidence
        },
        output_root=output_root,
        runtime_namespace_evidence_set=namespace_set,
        source_orchestration_evidence_set=orchestration_set,
        source_orchestration_validation_sources=(source_private,),
    )
    restored_batch = validate_causal_runtime_batch_v2(
        source_private.plan,
        manifest,
        profile,
        output_root=output_root,
    )

    source_runtime = source_result.runtime_evidence
    policy = source_private.policy
    contract = source_private.executor_contract
    source_worktree = source_private.worktree_safety_receipt
    source_request = source_private.execution_request
    source_resource = _resource(
        source_runtime,
        producer=contract.executor_identity_cid,
        meter=_identity("source-meter"),
        validator=_identity("source-resource-validator"),
    )
    source_record = G238ReplaySourceRecordV2.create(
        runtime_evidence=source_runtime,
        semantic_observation=G238SemanticObservationV2.create(
            source_runtime
        ),
        resource_receipt=source_resource,
    )
    source_index = G238ReplaySourceIndexV2.create(
        source_run_id=policy.run_id,
        source_commit=source_worktree.worktree_commit,
        recursive_gitlinks_cid=policy.recursive_gitlinks_cid,
        environment_cid=policy.environment_cid,
        route_manifest_cid=_identity("route-manifest"),
        case_index_cid=_identity("case-index"),
        run_plan_cid=_identity("run-plan"),
        source_worktree_cid=g240_worktree_safety_projection_cid(
            source_worktree
        ),
        source_executor_authority_cid=contract.executor_identity_cid,
        records=(source_record,),
    )

    replay_run_id = "g231-test-only-replay"
    launch = g240_replay_namespace_request_v2(
        source_policy=policy,
        source_receipt=source_result.runtime_namespace_receipt,
        replay_run_id=replay_run_id,
    )
    replay_execution_request = G240ExecutionRequestV2.create_replay(
        source_request,
        replay_run_id=replay_run_id,
        replay_process_namespace_cid=str(
            launch["replay_process_namespace_cid"]
        ),
        replay_state_namespace_cid=str(
            launch["replay_state_namespace_cid"]
        ),
        replay_output_namespace_cid=str(
            launch["replay_output_namespace_cid"]
        ),
        replay_cache_namespace_cids=launch[
            "replay_cache_namespace_cids"
        ],
        source_runtime_evidence=source_runtime,
        _test_only_synthetic_capability=(
            _G240_SYNTHETIC_TEST_CAPABILITY_V2
        ),
    )
    replay_executor = _identity("replay-executor")
    replay_observer = _identity("replay-observer")
    replay_orchestration_observer = _identity(
        "replay-orchestration-observer"
    )
    (
        replay_runtime,
        replay_namespace,
        replay_orchestration,
        replay_request,
        replay_receipt,
        replay_worktree,
    ) = run_g240_detached_replay_v2(
        source_worktree.source_checkout,
        source_worktree,
        policy,
        source_result.runtime_namespace_receipt,
        source_runtime,
        source_execution_request=source_request,
        replay_execution_request=replay_execution_request,
        replay_run_id=replay_run_id,
        executor_contract=contract,
        benchmark_root=root / "replay-state",
        replay_executor_identity_cid=replay_executor,
        replay_namespace_observer_identity_cid=replay_observer,
        orchestration_observer_identity_cid=(
            replay_orchestration_observer
        ),
        timeout_seconds=20,
        _test_only_synthetic_capability=(
            _G240_SYNTHETIC_TEST_CAPABILITY_V2
        ),
    )
    replay_payload = (
        canonical_dag_json_bytes(replay_runtime.to_dict()) + b"\n"
    )
    replay_private = G240PrivateReplayValidationSourcesV2(
        source_policy=policy,
        executor_contract=contract,
        source_namespace_receipt=(
            source_result.runtime_namespace_receipt
        ),
        namespace_receipt=replay_namespace,
        orchestration_receipt=replay_orchestration,
        source_worktree_safety_receipt=source_worktree,
        replay_request=replay_request,
        replay_receipt=replay_receipt,
        replay_worktree_safety_receipt=replay_worktree,
        evidence_payload=replay_payload,
    )
    replay_resource = _resource(
        replay_runtime,
        producer=replay_executor,
        meter=_identity("replay-meter"),
        validator=replay_observer,
    )
    detached_receipt = G238DetachedReplayReceiptV2.create(
        source_index=source_index,
        source_record=source_record,
        replay_run_id=replay_run_id,
        replay_worktree_cid=replay_namespace.replay_worktree_cid,
        source_namespace_receipt_cid=(
            source_result.runtime_namespace_receipt.receipt_cid
        ),
        source_process_namespace_cid=(
            source_result.runtime_namespace_receipt.process_namespace_cid
        ),
        source_state_namespace_cid=(
            source_result.runtime_namespace_receipt.state_namespace_cid
        ),
        source_cache_namespace_cid=g240_cache_namespace_set_cid(
            source_result.runtime_namespace_receipt.cache_namespace_cids
        ),
        replay_process_namespace_cid=(
            replay_namespace.replay_process_namespace_cid
        ),
        replay_state_namespace_cid=(
            replay_namespace.replay_state_namespace_cid
        ),
        replay_cache_namespace_cid=g240_cache_namespace_set_cid(
            replay_namespace.replay_cache_namespace_cids
        ),
        replay_executor_authority_cid=replay_executor,
        replay_validator_authority_cid=replay_observer,
        replay_runtime_evidence=replay_runtime,
        replay_semantic_observation=G238SemanticObservationV2.create(
            replay_runtime
        ),
        replay_resource_receipt=replay_resource,
    )
    operational_replay_sources = {
        source_record.record_cid: replay_private
    }
    replay_gate = build_g238_detached_replay_gate_v2(
        source_index,
        (detached_receipt,),
        validator_authority_cid=replay_observer,
        operational_replay_sources=operational_replay_sources,
    )
    composition = _test_only_composition_receipt(
        batch=batch,
        source_result=source_result,
        replay_gate=replay_gate,
    )
    return {
        "batch": batch,
        "restored_batch": restored_batch,
        "source_result": source_result,
        "source_request": source_request,
        "source_index": source_index,
        "detached_receipt": detached_receipt,
        "replay_request": replay_execution_request,
        "replay_gate": replay_gate,
        "replay_private": operational_replay_sources,
        "composition": composition,
    }


def test_g211_g240_g238_test_only_operational_conformance(
    test_only_operational_chain,
) -> None:
    chain = test_only_operational_chain
    source = chain["source_result"]
    batch = chain["batch"]
    restored = chain["restored_batch"]
    replay_gate = chain["replay_gate"]
    composition = chain["composition"]

    assert source.process_result.returncode == 0
    assert source.process_result.timed_out is False
    assert source.process_result.process_group_reaped is True
    assert source.orchestration_receipt.complete is True
    assert batch.complete is True
    assert restored.receipt_cid == batch.receipt_cid
    assert replay_gate["passed"] is True
    assert (
        validate_g238_detached_replay_gate_v2(
            replay_gate,
            chain["source_index"],
            (chain["detached_receipt"],),
            validator_authority_cid=(
                chain[
                    "detached_receipt"
                ].replay_validator_authority_cid
            ),
            operational_replay_sources=chain["replay_private"],
        )
        == replay_gate["receipt_cid"]
    )
    assert composition["schema"] == TEST_ONLY_COMPOSITION_SCHEMA
    assert composition["schema"] != G231_POSITIVE_GATE_BUNDLE_SCHEMA_V2
    assert composition["complete"] is True
    assert composition["passed"] is True
    assert composition["production_g231_authorized"] is False
    assert composition["holdout_authorized"] is False
    assert composition["holdout_accessed"] is False


def test_g231_production_boundary_rejects_test_only_execution(
    test_only_operational_chain,
) -> None:
    chain = test_only_operational_chain
    assert chain["source_request"].schema == (
        G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2
    )
    assert chain["replay_request"].schema == (
        G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2
    )
    for request in (
        chain["source_request"],
        chain["replay_request"],
    ):
        with pytest.raises(
            G240SourceExecutorError,
            match="production validation rejects test-only synthetic",
        ):
            validate_g240_production_execution_request_v2(request)

    # G231 calls this production validator before accepting persisted G211
    # operational sources.  Keep its public failure reason stable.
    with pytest.raises(
        PositiveGateBundleError,
        match=(
            "G231 production validation rejects test-only synthetic "
            "G240 execution"
        ),
    ):
        _validate_g211_g240_operational_sources(
            freeze=None,
            artifacts=None,
            matrix=None,
            g210_plans=(),
            pilot_runtime_batch=chain["batch"],
            development_runtime_batch=chain["batch"],
            source_orchestration_validation_sources={
                "pilot": (
                    chain["source_result"].validation_sources,
                ),
                "development": (
                    chain["source_result"].validation_sources,
                ),
            },
            resource_receipts=(),
        )
