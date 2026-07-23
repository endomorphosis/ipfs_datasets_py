"""Tests for structured Leanstral audit requests, responses, and cache."""

from __future__ import annotations

import hashlib
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
from ipfs_datasets_py.logic.modal.leanstral_artifact_cache import LeanstralArtifactCache
from ipfs_datasets_py.logic.modal.leanstral_audit import canonical_sha256
from ipfs_datasets_py.logic.modal.leanstral import (
    _logic_family_candidate_rejection_reason,
)


class _MemoryArtifactStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.writes: list[dict[str, object]] = []

    def write_file(
        self,
        data: bytes | str,
        filename: str | None = None,
        pin: bool = False,
    ) -> str:
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        identifier = f"mem-{hashlib.sha256(raw).hexdigest()[:16]}"
        self.objects[identifier] = raw
        self.writes.append({"filename": filename, "identifier": identifier, "pin": pin})
        return identifier

    def read_file(self, identifier: str) -> bytes | None:
        return self.objects.get(identifier)


class _FailingArtifactStorage:
    def write_file(
        self,
        data: bytes | str,
        filename: str | None = None,
        pin: bool = False,
    ) -> str:
        raise RuntimeError("distributed backend unavailable")

    def read_file(self, identifier: str) -> bytes | None:
        raise RuntimeError("distributed backend unavailable")


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
    assert validation.verified_by == ("leanstral-audit-schema-v3",)

    missing_counterexample = _response(request, counterexample=None, witness=None)
    rejected = validate_leanstral_audit_response(request, missing_counterexample)

    assert rejected.accepted is False
    assert "missing_counterexample_or_witness" in rejected.reasons

    zero_confidence = validate_leanstral_audit_response(
        request,
        _response(request, confidence=0.0),
    )
    assert zero_confidence.accepted is False
    assert "nonpositive_audit_confidence" in zero_confidence.reasons


def test_prompt_contract_uses_exact_ids_and_normalizes_null_abstention() -> None:
    request = _request()
    payload = request.to_prompt_payload()
    template = payload["response_template"]

    assert template["request_id"] == request.request_id
    assert template["proof_obligation_ids"] == [request.proof_obligation_ids[0]]
    assert template["abstention_reason"] is None
    assert payload["response_schema"]["optional"] == ("drafted_logic_candidates",)
    assert template["drafted_logic_candidates"] == []
    assert "candidate" in payload["drafted_logic_candidate_contract"]["required_fields"]
    assert (
        payload["drafted_logic_candidate_contract"]["required_values"][
            "source_copy_policy"
        ]
        == "reject_full_span_copy"
    )

    response = _response(request, abstention_reason="None")
    validation = validate_leanstral_audit_response(request, response)

    assert response.abstention_reason == ""
    assert validation.accepted is True


def test_audit_response_preserves_sanitized_drafted_logic_guidance() -> None:
    request = _request()
    response = _response(
        request,
        drafted_logic_candidates=[
            {
                "logic_family": "deontic",
                "candidate": (
                    "obligation(agency, notify(applicant)) "
                    "unless exception(emergency_review)"
                ),
                "proof_obligation_id": "PO-modal-001",
                "compiler_surface": "modal.ir_decompiler",
                "confidence": 0.72,
                "source_text": "The agency must notify the applicant unless emergency review applies.",
            },
            {
                "logic_family": "deontic",
                "candidate": (
                    "obligation(agency, notify(applicant)) "
                    "unless exception(emergency_review)"
                ),
                "proof_obligation_id": "PO-modal-001",
            },
        ],
    )

    validation = validate_leanstral_audit_response(request, response)
    candidates = response.to_dict()["drafted_logic_candidates"]

    assert validation.accepted is True
    assert len(candidates) == 1
    assert candidates[0]["intended_use"] == "guidance_only"
    assert candidates[0]["proof_obligation_id"] == "PO-modal-001"
    assert "source_text" not in candidates[0]


def test_audit_response_rejects_unknown_drafted_logic_obligations() -> None:
    request = _request()
    response = _response(
        request,
        drafted_logic_candidates=[
            {
                "logic_family": "tdfol",
                "candidate": "forall x. permitted(x)",
                "proof_obligation_id": "PO-not-in-request",
            }
        ],
    )

    validation = validate_leanstral_audit_response(request, response)

    assert validation.accepted is False
    assert "unknown_drafted_logic_proof_obligation_id" in validation.reasons


def test_audit_response_rejects_legacy_template_candidate() -> None:
    request = _request()
    response = _response(
        request,
        drafted_logic_candidates=[
            {
                "candidate": "obligation(actor, action) unless exception_condition",
                "confidence": 0.9,
                "logic_family": "deontic",
                "proof_obligation_id": "PO-modal-001",
            }
        ],
    )

    validation = validate_leanstral_audit_response(request, response)

    assert validation.accepted is False
    assert "template_copied_drafted_logic_candidate" in validation.reasons


def test_family_candidate_shape_distinguishes_tdfol_dcec_and_flogic() -> None:
    assert not _logic_family_candidate_rejection_reason(
        "temporal_anchor(event:e1, time:t1)",
        "temporal_first_order",
        "TDFOL.prover",
    )
    assert not _logic_family_candidate_rejection_reason(
        "initiates(event:e1, fluent:f1, time:t1)",
        "event_calculus",
        "CEC.native",
    )
    assert not _logic_family_candidate_rejection_reason(
        "frame_role(subject:agency, role:notice, object:person)",
        "frame_logic",
        "modal.frame_logic",
    )
    assert _logic_family_candidate_rejection_reason(
        "frame_role(subject:agency, role:notice, object:person)",
        "event_calculus",
        "CEC.native",
    ) == "dcec_candidate_shape_mismatch"


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


def test_cache_uses_distributed_artifact_cache_as_local_miss_fallback(tmp_path) -> None:
    request = _request()
    response = _response(request)
    validation = validate_leanstral_audit_response(request, response)
    storage = _MemoryArtifactStorage()
    artifact_cache = LeanstralArtifactCache(
        index_path=tmp_path / "artifact-index.json",
        storage=storage,
        pin=True,
    )
    local_dir = tmp_path / "local"
    cache = LeanstralAuditCache(local_dir, artifact_cache=artifact_cache)

    cache.put(request, response, validation)

    assert len(storage.writes) == 1
    assert storage.writes[0]["filename"] == f"{request.cache_key}.json"
    assert storage.writes[0]["pin"] is True
    local_path = local_dir / f"{request.cache_key}.json"
    local_path.unlink()
    cold_cache = LeanstralAuditCache(local_dir, artifact_cache=artifact_cache)
    restored = cold_cache.get_accepted(request)

    assert restored is not None
    assert restored.content_hash == response.content_hash
    assert local_path.is_file()


def test_cache_rejects_corrupted_distributed_artifact(tmp_path) -> None:
    request = _request()
    response = _response(request)
    validation = validate_leanstral_audit_response(request, response)
    storage = _MemoryArtifactStorage()
    artifact_cache = LeanstralArtifactCache(
        index_path=tmp_path / "artifact-index.json",
        storage=storage,
    )
    local_dir = tmp_path / "local"
    cache = LeanstralAuditCache(local_dir, artifact_cache=artifact_cache)

    cache.put(request, response, validation)
    (local_dir / f"{request.cache_key}.json").unlink()
    index = json.loads((tmp_path / "artifact-index.json").read_text(encoding="utf-8"))
    index["artifacts"][request.cache_key]["sha256"] = "0" * 64
    (tmp_path / "artifact-index.json").write_text(json.dumps(index), encoding="utf-8")
    cold_cache = LeanstralAuditCache(local_dir, artifact_cache=artifact_cache)

    assert cold_cache.get_accepted(request) is None


def test_distributed_artifact_cache_failures_do_not_block_local_cache(tmp_path) -> None:
    request = _request()
    response = _response(request)
    validation = validate_leanstral_audit_response(request, response)
    artifact_cache = LeanstralArtifactCache(
        index_path=tmp_path / "artifact-index.json",
        storage=_FailingArtifactStorage(),
    )
    cache = LeanstralAuditCache(tmp_path / "local", artifact_cache=artifact_cache)

    cache.put(request, response, validation)
    restored = cache.get_accepted(request)

    assert restored is not None
    assert restored.content_hash == response.content_hash


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
    assert calls[0]["provider"] == "leanstral_local"
    assert calls[0]["model_name"] == "Leanstral"


def test_audit_runner_repairs_schema_invalid_response_once(tmp_path) -> None:
    calls: list[dict[str, object]] = []

    def fake_generate(prompt: str, **kwargs: object) -> str:
        payload = json.loads(prompt)
        request_payload = payload["request"]
        calls.append(payload)
        request = LeanstralAuditRequest.build(
            evidence=request_payload["evidence"],
            prompt=request_payload["prompt"],
            model=request_payload["model"],
            theorem_registry_hash=request_payload["theorem_registry_hash"],
            proof_obligation_ids=request_payload["proof_obligation_ids"],
        )
        if len(calls) == 1:
            return json.dumps(
                _response(
                    request,
                    proposed_compiler_surface=[],
                    counterexample=None,
                    witness=None,
                ).to_dict()
            )
        assert payload["repair_instructions"]["mode"] == "validation_repair"
        assert "missing_counterexample_or_witness" in payload["repair_instructions"][
            "validation_reasons"
        ]
        assert "missing_proposed_compiler_surface" in payload["repair_instructions"][
            "validation_reasons"
        ]
        return json.dumps(_response(request).to_dict())

    config = LeanstralAuditConfig(
        enabled=True,
        cache_dir=str(tmp_path),
        validation_repair_retries=1,
    )
    runner = LeanstralAuditRunner(config, llm_generate=fake_generate)

    result = runner.run(
        evidence={"evidence_id": "projection-abc", "modal_ir_hash": "a" * 64},
        prompt={"template": "audit"},
        theorem_registry={"registry_id": "legal-ir-theorems-v1"},
        proof_obligation_ids=("PO-modal-001",),
    )

    assert result.validation.accepted is True
    assert result.generation_attempts == 2
    assert "missing_counterexample_or_witness" in result.repair_reasons
    assert "missing_proposed_compiler_surface" in result.repair_reasons
    assert len(calls) == 2


def test_request_accepts_precomputed_theorem_registry_hash() -> None:
    registry_hash = canonical_sha256({"registry_id": "legal-ir-theorems-v1"})

    request = _request(theorem_registry=None, theorem_registry_hash=registry_hash)

    assert request.theorem_registry_hash == registry_hash
