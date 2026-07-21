"""Unit coverage for cache-first continuous Leanstral batching."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.logic.modal.leanstral_audit import (
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LeanstralAuditCache,
    LeanstralAuditResponse,
    LeanstralAuditValidation,
    LeanstralAuditWorker,
    LeanstralAuditWorkerConfig,
    LeanstralAuditWorkItem,
    LeanstralAuditRequest,
    validate_leanstral_audit_response,
)
from ipfs_datasets_py.logic.modal.leanstral_audit_worker import (
    LeanstralBatchSchedulerConfig,
    LeanstralContinuousBatchService,
    LeanstralContinuousBatchServiceConfig,
    LeanstralQueueBackpressureError,
    LeanstralServiceHealth,
    estimate_leanstral_audit_tokens,
    probe_reusable_cuda_leanstral_service,
)
from ipfs_datasets_py.utils import anyio_compat


def _request(index: int, family: str = "deontic") -> LeanstralAuditRequest:
    return LeanstralAuditRequest.build(
        evidence={
            "cluster": {
                "gaps": [{"gap_id": f"gap-{index}"}],
                "leanstral_audit_policy": {
                    "formal_severity": 0.2,
                    "heldout_impact": 0.3,
                    "rank_score": 0.4,
                },
                "semantic_family": family,
            }
        },
        prompt={"template": "modal_operator_preserved", "index": index},
        model={
            "model": "Leanstral",
            "provider": "leanstral_local",
            "vibe_agent": "lean",
        },
        proof_obligation_ids=[f"obl-{index}"],
    )


def _response_json(request: LeanstralAuditRequest) -> str:
    return json.dumps(
        {
            "abstention_reason": "insufficient verified evidence",
            "affected_ir_families": ["deontic"],
            "classification": "abstain",
            "confidence": 0.0,
            "counterexample": None,
            "drafted_logic_candidates": [],
            "missing_semantic_rule": {},
            "proof_obligation_ids": list(request.proof_obligation_ids),
            "proposed_compiler_surface": [],
            "request_cache_key": request.cache_key,
            "request_id": request.request_id,
            "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            "witness": None,
        },
        sort_keys=True,
    )


def _request_from_prompt(prompt: str) -> dict:
    begin = "BEGIN_REQUEST_JSON"
    end = "END_REQUEST_JSON"
    begin_index = prompt.index(begin) + len(begin)
    end_index = prompt.index(end, begin_index)
    return json.loads(prompt[begin_index:end_index].strip())


def _item(request: LeanstralAuditRequest, index: int) -> LeanstralAuditWorkItem:
    return LeanstralAuditWorkItem(
        work_key=f"work-{index}",
        request=request,
        evidence_ids=(f"evidence-{index}",),
        compiler_commit="commit-a",
        semantic_signature="deontic:test",
        state_hashes=("state-a",),
        source_record_hashes=(f"record-{index}",),
    )


def _healthy_service() -> LeanstralServiceHealth:
    return LeanstralServiceHealth(
        status="healthy",
        cuda_backed=True,
        provider="leanstral_local",
        model="Leanstral",
        base_url="http://127.0.0.1:8080/v1",
        service_id="unit-test-leanstral",
    )


def test_continuous_service_checks_cache_before_queue_admission(tmp_path) -> None:
    cached_request = _request(1)
    miss_request = _request(2)
    cached_response = LeanstralAuditResponse.from_mapping(json.loads(_response_json(cached_request)))
    validation = validate_leanstral_audit_response(cached_request, cached_response)
    assert validation.accepted and validation.verified

    cache = LeanstralAuditCache(tmp_path / "cache")
    cache.put(cached_request, cached_response, validation)
    batch_calls: list[int] = []

    def generate_batch(prompts: list[str], **kwargs: object) -> list[str]:
        del kwargs
        batch_calls.append(len(prompts))
        known = {
            cached_request.request_id: cached_request,
            miss_request.request_id: miss_request,
        }
        return [
            _response_json(known[_request_from_prompt(prompt)["request_id"]])
            for prompt in prompts
        ]

    worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            batch_size=4,
            cache_dir=str(tmp_path / "cache"),
            max_retries=0,
            validation_repair_retries=0,
        ),
        llm_generate_batch=generate_batch,
    )
    service = LeanstralContinuousBatchService(worker, health=_healthy_service())

    results = anyio_compat.run_with_backend(
        service.run_items([_item(cached_request, 1), _item(miss_request, 2)])
    )
    telemetry = service.telemetry_snapshot()

    assert [result.status for result in results] == ["cache_hit", "accepted"]
    assert batch_calls == [1]
    assert telemetry["cache_hit_count"] == 1
    assert telemetry["formed_batch_count"] == 1
    assert telemetry["cache_value_tokens"] >= estimate_leanstral_audit_tokens(
        cached_request,
        max_new_tokens=worker.config.bounded_max_new_tokens(),
    )
    assert telemetry["proof_authority"] is False
    assert telemetry["continuous_service"]["health"]["proof_authority"] is False


def test_continuous_service_fair_batches_and_preserves_item_retries(tmp_path) -> None:
    requests = [_request(1, "deontic"), _request(2, "deontic"), _request(3, "temporal")]
    call_sizes: list[int] = []

    def generate_batch(prompts: list[str], **kwargs: object) -> list[str]:
        del kwargs
        call_sizes.append(len(prompts))
        known = {request.request_id: request for request in requests}
        request_payloads = [known[_request_from_prompt(prompt)["request_id"]] for prompt in prompts]
        if len(prompts) == 2:
            return [_response_json(request_payloads[0]), "not json"]
        return [_response_json(request_payloads[0])]

    worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            batch_size=2,
            cache_dir=str(tmp_path / "cache"),
            max_retries=0,
            validation_repair_retries=1,
        ),
        llm_generate_batch=generate_batch,
    )
    service = LeanstralContinuousBatchService(
        worker,
        LeanstralContinuousBatchServiceConfig(
            scheduler=LeanstralBatchSchedulerConfig(max_batch_size=2),
        ),
        health=_healthy_service(),
    )

    results = anyio_compat.run_with_backend(
        service.run_items([_item(request, index) for index, request in enumerate(requests, 1)])
    )
    telemetry = service.telemetry_snapshot()

    assert [result.request_id for result in results] == [request.request_id for request in requests]
    assert [result.status for result in results] == ["accepted", "accepted", "accepted"]
    assert results[1].attempts == 2
    assert results[1].generation_attempts == 2
    assert call_sizes == [2, 1, 1]
    assert telemetry["family_dispatch_counts"] == {"deontic": 2, "temporal": 1}
    assert telemetry["verified_audit_count"] == 3
    assert telemetry["tokens_per_gpu_second"] >= 0.0
    assert telemetry["marginal_information_per_gpu_second"] >= 0.0


def test_continuous_service_applies_queue_backpressure(tmp_path) -> None:
    worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            batch_size=2,
            cache_dir=str(tmp_path / "cache"),
            max_retries=0,
        ),
        llm_generate_batch=lambda prompts, **kwargs: [],
    )
    service = LeanstralContinuousBatchService(
        worker,
        LeanstralContinuousBatchServiceConfig(
            scheduler=LeanstralBatchSchedulerConfig(max_batch_size=2),
            max_queue_items=1,
        ),
        health=_healthy_service(),
    )

    async def submit_two() -> None:
        service.submit(_item(_request(1), 1))
        with pytest.raises(LeanstralQueueBackpressureError) as exc_info:
            service.submit(_item(_request(2), 2))
        assert exc_info.value.reason == "leanstral_queue_backpressure"

    anyio_compat.run_with_backend(submit_two())

    assert service.telemetry_snapshot()["backpressure_rejection_count"] == 1


def test_cuda_service_probe_reports_no_proof_authority() -> None:
    health = probe_reusable_cuda_leanstral_service(
        env={
            "IPFS_ACCELERATE_LLAMA_CPP_BASE_URL": "http://127.0.0.1:8080/v1",
            "IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS": "auto",
            "LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER": "1",
        }
    )

    assert health.healthy_cuda_backed
    assert health.proof_authority is False
    assert health.to_dict()["service_id"].startswith("leanstral-service-")
