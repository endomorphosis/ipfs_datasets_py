"""Tests for Leanstral batch and mesh inference routing."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.modal.leanstral_audit import (
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LeanstralAuditConfig,
    LeanstralAuditRequest,
    LeanstralAuditRunner,
    leanstral_llm_router_health,
    resolve_leanstral_llm_router,
)


def _request(index: int) -> LeanstralAuditRequest:
    return LeanstralAuditRequest.build(
        evidence={"cluster": {"compiler_surface": "deontic.ir"}},
        prompt={"prompt": f"request {index}"},
        model={
            "model": "Leanstral",
            "provider": "leanstral_local",
            "vibe_agent": "lean",
        },
        proof_obligation_ids=[f"obl-{index}"],
    )


def _abstain_response(request: LeanstralAuditRequest) -> str:
    return json.dumps(
        {
            "abstention_reason": "insufficient evidence",
            "affected_ir_families": ["deontic"],
            "classification": "abstain",
            "confidence": 0.0,
            "counterexample": None,
            "drafted_logic_candidates": [],
            "missing_semantic_rule": {},
            "proof_obligation_ids": [request.proof_obligation_ids[0]],
            "proposed_compiler_surface": [],
            "request_cache_key": request.cache_key,
            "request_id": request.request_id,
            "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            "witness": None,
        },
        sort_keys=True,
    )


def test_leanstral_batch_defaults_to_ipfs_accelerate_mesh_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = [_request(1), _request(2)]
    calls: list[dict[str, object]] = []

    def fake_generate_text_batch(prompts: list[str], **kwargs: object) -> list[str]:
        calls.append({"prompts": prompts, **kwargs})
        return [_abstain_response(request) for request in requests]

    fake_router = SimpleNamespace(
        __name__="ipfs_accelerate_py.llm_router",
        generate_text=lambda prompt, **kwargs: _abstain_response(requests[0]),
        generate_text_batch=fake_generate_text_batch,
        get_last_generation_trace=lambda: {
            "effective_provider_name": "leanstral_local"
        },
    )

    def fake_import_module(name: str) -> object:
        if name == "ipfs_accelerate_py.llm_router":
            return fake_router
        raise ImportError(name)

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.leanstral_audit.importlib.import_module",
        fake_import_module,
    )
    runner = LeanstralAuditRunner(
        LeanstralAuditConfig(
            enabled=True,
            provider="leanstral_local",
            model="Leanstral",
            cache_writes_enabled=False,
            validation_repair_retries=0,
        )
    )

    results = runner.run_initial_batch(
        requests,
        use_mesh=True,
        max_workers=7,
    )

    assert len(results) == 2
    assert all(result.validation.accepted for result in results)
    assert calls[0]["use_mesh"] is True
    assert calls[0]["max_workers"] == 7
    assert calls[0]["provider"] == "leanstral_local"
    assert calls[0]["model_name"] == "Leanstral"
    assert "llm_router:ipfs_accelerate_py" in results[0].repair_reasons
    assert "llm_router_mode:mesh_batch" in results[0].repair_reasons
    assert (
        "llm_router_effective_provider:leanstral_local"
        in results[0].repair_reasons
    )


def test_leanstral_router_resolver_reports_fallback_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_datasets_router = SimpleNamespace(
        __name__="ipfs_datasets_py.llm_router",
        generate_text=lambda prompt, **kwargs: "{}",
        generate_text_batch=lambda prompts, **kwargs: ["{}" for _ in prompts],
    )

    def fake_import_module(name: str) -> object:
        if name == "ipfs_accelerate_py.llm_router":
            raise ImportError("accelerate unavailable")
        if name == "ipfs_datasets_py.llm_router":
            return fake_datasets_router
        raise ImportError(name)

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.leanstral_audit.importlib.import_module",
        fake_import_module,
    )

    router, health = resolve_leanstral_llm_router()

    assert router is fake_datasets_router
    assert health["router"] == "ipfs_datasets_py"
    assert health["generate_text_batch_available"] is True
    assert health["trace_available"] is False
    assert health["attempts"][0]["module"] == "ipfs_accelerate_py.llm_router"


def test_leanstral_router_health_handles_missing_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.modal.leanstral_audit.importlib.import_module",
        lambda name: (_ for _ in ()).throw(ImportError(name)),
    )

    health = leanstral_llm_router_health()

    assert health["status"] == "unavailable"
    assert "ImportError" in health["error"]
