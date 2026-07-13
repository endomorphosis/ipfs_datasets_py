"""Tests for structured Leanstral audit requests, responses, and cache."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.modal import (
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LeanstralAuditCache,
    LeanstralAuditConfig,
    LeanstralAuditRequest,
    LeanstralAuditResponse,
    LeanstralAuditRunner,
    build_leanstral_audit_cache_key,
    parse_leanstral_audit_response,
    validate_leanstral_audit_response,
)
from ipfs_datasets_py.logic.modal.leanstral_audit import canonical_sha256


def _request(**overrides):
    kwargs = {
        "evidence": {
            "evidence_id": "projection-abc",
            "modal_ir_hash": "a" * 64,
            "source_span_hashes": {"f1": "b" * 64},
            "legal_ir_view_gaps": {"deontic_norms": 0.42},
        },
        "prompt": {
            "template": "audit missing legal IR semantics",
            "instructions_hash": "c" * 64,
        },
        "model": {
            "provider": "mistral_vibe",
            "model": "Leanstral",
            "vibe_agent": "lean",
        },
        "theorem_registry": {
            "registry_id": "legal-ir-theorems-v1",
            "templates": ["modal_operator_preserved", "exception_scope_preserved"],
        },
        "proof_obligation_ids": ("PO-modal-001", "PO-exception-002"),
    }
    kwargs.update(overrides)
    return LeanstralAuditRequest.build(**kwargs)


def _response(request: LeanstralAuditRequest, **overrides) -> LeanstralAuditResponse:
    data = {
        "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
        "request_id": request.request_id,
        "request_cache_key": request.cache_key,
        "classification": "missing_semantic_rule",
        "missing_semantic_rule": {
            "rule_id": "deontic_exception_scope",
            "description": "Preserve exception clauses under obligation scope.",
        },
        "counterexample": {
            "source": "The agency must notify the applicant unless emergency review applies.",
            "compiler_output": "obligation(notify)",
            "expected": "obligation(notify unless emergency_review)",
        },
        "witness": None,
        "affected_ir_families": ["deontic", "temporal"],
        "proposed_compiler_surface": [
            {
                "component": "modal.ir_decompiler",
                "paths": [
                    "ipfs_datasets_py/logic/modal/codec.py",
                    "ipfs_datasets_py/logic/modal/decompiler.py",
                ],
                "operation": "refine exception scope extraction",
            }
        ],
        "confidence": 0.84,
        "proof_obligation_ids": ["PO-modal-001"],
        "abstention_reason": "",
        "rationale": "The source span contains an explicit exception cue.",
    }
    data.update(overrides)
    return LeanstralAuditResponse.from_mapping(data)


def test_audit_request_cache_key_covers_all_required_hash_axes() -> None:
    base = _request()
    changed_evidence = _request(evidence={**base.evidence, "new_gap": 0.1})
    changed_prompt = _request(prompt={**base.prompt, "template": "different"})
    changed_model = _request(model={**base.model, "model": "Leanstral-next"})
    changed_registry = _request(theorem_registry={"registry_id": "other"})

    assert len(base.cache_key) == 64
    assert base.cache_key != changed_evidence.cache_key
    assert base.cache_key != changed_prompt.cache_key
    assert base.cache_key != changed_model.cache_key
    assert base.cache_key != changed_registry.cache_key

    schema_changed = build_leanstral_audit_cache_key(
        evidence_hash=base.evidence_hash,
        prompt_hash=base.prompt_hash,
        model_hash=base.model_hash,
        theorem_registry_hash=base.theorem_registry_hash,
        request_schema_hash="0" * 64,
        response_schema_hash=base.response_schema_hash,
    )
    assert schema_changed != base.cache_key


def test_audit_response_validation_requires_machine_readable_evidence() -> None:
    request = _request()
    response = _response(request)

    validation = validate_leanstral_audit_response(request, response)

    assert validation.accepted is True
    assert validation.verified is True
    assert validation.response_hash == response.content_hash
    assert validation.verified_by == ("leanstral-audit-schema-v1",)

    missing_counterexample = _response(request, counterexample=None, witness=None)
    rejected = validate_leanstral_audit_response(request, missing_counterexample)

    assert rejected.accepted is False
    assert "missing_counterexample_or_witness" in rejected.reasons


def test_prompt_contract_uses_exact_ids_and_normalizes_null_abstention() -> None:
    request = _request()
    payload = request.to_prompt_payload()
    template = payload["response_template"]

    assert template["request_id"] == request.request_id
    assert template["proof_obligation_ids"] == [request.proof_obligation_ids[0]]
    assert template["abstention_reason"] is None

    response = _response(request, abstention_reason="None")
    validation = validate_leanstral_audit_response(request, response)

    assert response.abstention_reason == ""
    assert validation.accepted is True


def test_abstention_requires_reason_and_malformed_json_is_not_a_response() -> None:
    request = _request()
    malformed = parse_leanstral_audit_response("not json")

    invalid_json = validate_leanstral_audit_response(request, malformed)

    assert malformed is None
    assert invalid_json.accepted is False
    assert invalid_json.verified is False
    assert "invalid_json_audit_response" in invalid_json.reasons

    abstention = _response(
        request,
        classification="abstain",
        missing_semantic_rule={},
        counterexample=None,
        witness=None,
        proposed_compiler_surface=[],
        abstention_reason="",
    )

    rejected = validate_leanstral_audit_response(request, abstention)

    assert rejected.accepted is False
    assert "missing_abstention_reason" in rejected.reasons


def test_cache_returns_only_current_verified_entries(tmp_path) -> None:
    request = _request()
    response = _response(request)
    validation = validate_leanstral_audit_response(request, response)
    cache = LeanstralAuditCache(tmp_path)

    entry = cache.put(request, response, validation)

    assert cache.get_accepted(request) == response
    assert entry.request_hash == request.content_hash

    path = tmp_path / f"{request.cache_key}.json"
    payload = entry.to_dict()
    payload["validation"] = {
        **payload["validation"],
        "verified": False,
        "verified_by": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    cache = LeanstralAuditCache(tmp_path)
    assert cache.get_accepted(request) is None

    stale_payload = entry.to_dict()
    stale_payload["request_hash"] = "0" * 64
    path.write_text(json.dumps(stale_payload), encoding="utf-8")
    cache = LeanstralAuditCache(tmp_path)
    assert cache.get_accepted(request) is None

    tampered_payload = entry.to_dict()
    tampered_payload["response"]["confidence"] = 0.1
    path.write_text(json.dumps(tampered_payload), encoding="utf-8")
    cache = LeanstralAuditCache(tmp_path)
    assert cache.get_accepted(request) is None

    path.write_text("{", encoding="utf-8")
    cache = LeanstralAuditCache(tmp_path)
    assert cache.get_accepted(request) is None


def test_audit_runner_uses_verified_content_addressed_cache(tmp_path) -> None:
    calls: list[dict[str, object]] = []

    def fake_generate(prompt: str, **kwargs: object) -> str:
        request_payload = json.loads(prompt)["request"]
        calls.append({"prompt": prompt, **kwargs})
        response = _response(
            LeanstralAuditRequest.build(
                evidence=request_payload["evidence"],
                prompt=request_payload["prompt"],
                model=request_payload["model"],
                theorem_registry_hash=request_payload["theorem_registry_hash"],
                proof_obligation_ids=request_payload["proof_obligation_ids"],
            )
        )
        return json.dumps(response.to_dict())

    config = LeanstralAuditConfig(enabled=True, cache_dir=str(tmp_path))
    runner = LeanstralAuditRunner(config, llm_generate=fake_generate)

    kwargs = {
        "evidence": {"evidence_id": "projection-abc", "modal_ir_hash": "a" * 64},
        "prompt": {"template": "audit"},
        "theorem_registry": {"registry_id": "legal-ir-theorems-v1"},
        "proof_obligation_ids": ("PO-modal-001",),
    }
    first = runner.run(**kwargs)
    second = runner.run(**kwargs)

    assert first.llm_called is True
    assert first.validation.accepted is True
    assert second.llm_called is False
    assert second.cache_hit is True
    assert second.validation.accepted is True
    assert len(calls) == 1
    assert calls[0]["provider"] == "mistral_vibe"
    assert calls[0]["model_name"] == "Leanstral"


def test_request_accepts_precomputed_theorem_registry_hash() -> None:
    registry_hash = canonical_sha256({"registry_id": "legal-ir-theorems-v1"})

    request = _request(theorem_registry=None, theorem_registry_hash=registry_hash)

    assert request.theorem_registry_hash == registry_hash
