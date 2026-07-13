"""Tests for the bounded asynchronous Leanstral audit worker."""

from __future__ import annotations

import asyncio
import errno
import json
import threading
import time
from dataclasses import replace

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LeanstralAuditRequest,
    LeanstralAuditResponse,
    LeanstralAuditValidation,
    LeanstralAuditWorker,
    LeanstralAuditWorkerConfig,
    LeanstralVerifierConfig,
    ModalLogicCodecConfig,
    build_leanstral_audit_work_items,
    load_leanstral_audit_disagreements,
)
from ipfs_datasets_py.logic.modal.leanstral_audit import canonical_sha256
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from scripts.ops.legal_ir.run_leanstral_audit_worker import verify_worker_audit_outputs


def _packet(index: int, *, state_hash: str = "state-a", component: str = "deontic") -> dict:
    evidence_id = f"evidence-{index:03d}"
    sample_id = f"sample-{index:03d}"
    modal_hash = canonical_sha256({"modal": sample_id})
    source_span_hash = canonical_sha256({"span": sample_id})
    return {
        "anti_copy_evidence": {
            "dense_weight_tables_included": False,
            "source_span_copy_ratio": 0.0,
            "stripped_dense_input_key_hashes": [],
        },
        "compiler_decompiler_metrics": {
            "cross_entropy_loss": 0.31 + index * 0.01,
            "cosine_similarity": 0.7,
        },
        "evidence_hashes": {
            "canonical_modal_ir_hash": modal_hash,
            "causal_feature_attribution_hash": canonical_sha256({"causal": sample_id}),
            "compiler_guidance_hash": canonical_sha256({"guidance": sample_id}),
            "compiler_metrics_hash": canonical_sha256({"metrics": sample_id}),
            "learned_view_gaps_hash": canonical_sha256({"learned": sample_id}),
            "proof_route_hash": canonical_sha256({"proof": sample_id}),
            "source_span_hashes_hash": canonical_sha256({"spans": [source_span_hash]}),
            "state_hash": state_hash,
        },
        "evidence_id": evidence_id,
        "legal_ir_component_gaps": {
            f"{component}.obligation_scope": 0.42 + index * 0.01,
        },
        "legal_ir_views": {
            "canonical": {
                "family_distribution": {"deontic": 1.0},
                "modal_ir_hash": modal_hash,
            },
            "predicted": {
                "family_distribution": {"temporal": 0.8},
                "predicted_family": "temporal",
                "target_family": "deontic",
            },
        },
        "learned_view_gaps": {"deontic": 0.42},
        "proof_route_status": {
            "attempted_count": 1,
            "compiles": True,
            "route_status": "compiled",
            "valid_count": 1,
        },
        "run_context": {
            "compiler_commit": "commit-a",
            "cycle": index,
            "evaluation_role": "guided",
            "frozen_canary": {"canary_id": "canary-a"},
            "sample_role": "holdout",
            "state_hash": state_hash,
        },
        "sample_hashes": {
            "modal_ir_hash": modal_hash,
            "normalized_text_hash": canonical_sha256({"normalized": sample_id}),
            "sample_id": sample_id,
            "source_span_hashes": {"formula": source_span_hash},
            "source_text_hash": canonical_sha256({"source": sample_id}),
        },
        "schema_version": "legal-ir-introspection-packet-v1",
    }


def _response_json(request_payload: dict) -> str:
    request = LeanstralAuditRequest.build(
        evidence=request_payload["evidence"],
        prompt=request_payload["prompt"],
        model=request_payload["model"],
        theorem_registry_hash=request_payload["theorem_registry_hash"],
        proof_obligation_ids=request_payload["proof_obligation_ids"],
    )
    return json.dumps(
        {
            "abstention_reason": "",
            "affected_ir_families": ["deontic"],
            "classification": "missing_semantic_rule",
            "confidence": 0.82,
            "counterexample": {"source_span_hash": "abc", "expected": "obligation_with_exception"},
            "missing_semantic_rule": {"rule_id": "obligation_scope"},
            "proof_obligation_ids": [request.proof_obligation_ids[0]],
            "proposed_compiler_surface": [{"component": "deontic.ir", "operation": "preserve scope"}],
            "request_cache_key": request.cache_key,
            "request_id": request.request_id,
            "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            "witness": None,
        }
    )


def test_worker_loads_jsonl_clusters_and_deduplicates_required_axes(tmp_path) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _packet(1)
    path.write_text(json.dumps(packet) + "\n" + json.dumps(packet) + "\n", encoding="utf-8")

    records, failures, source_digest = load_leanstral_audit_disagreements([path])
    items, stale = build_leanstral_audit_work_items(
        records,
        config=LeanstralAuditWorkerConfig(cache_dir=str(tmp_path / "cache")),
    )

    assert failures == []
    assert stale == []
    assert source_digest
    assert len(items) == 1
    item = items[0]
    assert item.compiler_commit == "commit-a"
    assert item.semantic_signature
    assert item.request.model["model"] == "Leanstral"
    assert item.request.request_schema_hash
    assert item.request.response_schema_hash


def test_worker_bounds_model_evidence_and_preserves_full_hash_manifest(tmp_path) -> None:
    packets = [_packet(index) for index in range(1, 13)]
    items, stale = build_leanstral_audit_work_items(
        packets,
        config=LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "cache"),
            max_evidence_packets_per_item=2,
        ),
    )

    assert stale == []
    truncated = [
        item
        for item in items
        if item.request.evidence.get("evidence_packet_count", 0) > 2
    ]
    assert truncated
    for item in truncated:
        evidence = item.request.evidence
        assert len(evidence["evidence_packets"]) == 2
        assert evidence["evidence_packet_selection"] == "ranked_prefix_with_full_hash_manifest"
        assert len(evidence["source_record_hashes"]) == evidence["evidence_packet_count"]
        assert len(evidence["omitted_evidence_packet_hashes"]) == (
            evidence["evidence_packet_count"] - 2
        )


def test_worker_runs_bounded_async_audits_and_reuses_checkpoint_and_cache(tmp_path) -> None:
    active = 0
    max_active = 0
    calls = 0
    lock = threading.Lock()

    def fake_generate(prompt: str, **kwargs: object) -> str:
        nonlocal active, max_active, calls
        with lock:
            active += 1
            calls += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        assert kwargs["allow_local_fallback"] is False
        assert kwargs["model_name"] == "Leanstral"
        return _response_json(json.loads(prompt)["request"])

    packets = [_packet(1, component="deontic"), _packet(2, component="temporal")]
    config = LeanstralAuditWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        checkpoint_path=str(tmp_path / "checkpoint.json"),
        max_concurrency=1,
        max_retries=0,
        request_timeout_seconds=2.0,
    )
    worker = LeanstralAuditWorker(config, llm_generate=fake_generate)

    first = asyncio.run(worker.run_records(packets, source_digest="source-a"))
    second = asyncio.run(worker.run_records(packets, source_digest="source-a"))

    assert first.completed_count == 2
    assert first.llm_call_count == 2
    assert max_active == 1
    assert (tmp_path / "checkpoint.json").is_file()
    assert second.skipped_checkpoint_count == 2
    assert calls == 2


def test_worker_retries_timeouts_and_reports_labs_unavailable(tmp_path) -> None:
    calls = 0

    def flaky_generate(prompt: str, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient transport failure")
        return _response_json(json.loads(prompt)["request"])

    retry_worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "retry-cache"),
            max_concurrency=1,
            max_retries=1,
            request_timeout_seconds=2.0,
            retry_backoff_seconds=0.0,
        ),
        llm_generate=flaky_generate,
    )
    retry_summary = asyncio.run(retry_worker.run_records([_packet(1)], source_digest="retry"))
    assert retry_summary.completed_count == 1
    assert retry_summary.results[0].attempts == 2

    def unavailable_generate(prompt: str, **kwargs: object) -> str:
        raise PermissionError("Leanstral Labs model access unavailable")

    unavailable_worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "unavailable-cache"),
            max_retries=2,
            request_timeout_seconds=2.0,
        ),
        llm_generate=unavailable_generate,
    )
    unavailable = asyncio.run(unavailable_worker.run_records([_packet(2)], source_digest="unavailable"))
    assert unavailable.unavailable_count == 1
    assert unavailable.results[0].reasons == ("leanstral_labs_model_unavailable",)

    def oversized_generate(prompt: str, **kwargs: object) -> str:
        raise OSError(errno.E2BIG, "Argument list too long")

    oversized_worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "oversized-cache"),
            max_retries=0,
            request_timeout_seconds=2.0,
        ),
        llm_generate=oversized_generate,
    )
    oversized = asyncio.run(
        oversized_worker.run_records([_packet(3)], source_digest="oversized")
    )
    assert oversized.failed_count == 1
    assert oversized.results[0].reasons == (
        "provider_error:OSError:argument_list_too_long",
    )


def test_worker_rejects_stale_state_and_non_leanstral_model(tmp_path) -> None:
    stale_worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "cache"),
            expected_state_hash="current-state",
        ),
        llm_generate=lambda prompt, **kwargs: _response_json(json.loads(prompt)["request"]),
    )
    stale = asyncio.run(stale_worker.run_records([_packet(1, state_hash="old-state")], source_digest="stale"))
    assert stale.work_item_count == 0
    assert stale.stale_state_rejections[0]["reason"] == "stale_state_hash"

    generic_worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "generic-cache"),
            model="Mistral-Large",
        ),
        llm_generate=lambda prompt, **kwargs: _response_json(json.loads(prompt)["request"]),
    )
    generic = asyncio.run(generic_worker.run_records([_packet(2)], source_digest="generic"))
    assert generic.rejected_count == 1
    assert generic.results[0].status == "model_rejected"
    assert generic.results[0].llm_called is False


def test_worker_verifies_cached_real_audits_into_rule_gap_report(tmp_path) -> None:
    path = tmp_path / "packets.jsonl"
    path.write_text(json.dumps(_packet(1)) + "\n", encoding="utf-8")
    records, failures, _ = load_leanstral_audit_disagreements([path])
    assert failures == []

    config = LeanstralAuditWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        provider_enabled=False,
    )
    worker = LeanstralAuditWorker(config)
    items, stale = build_leanstral_audit_work_items(records, config=config)
    assert stale == []
    item = items[0]
    sample = _modal_sample()
    response = LeanstralAuditResponse.from_mapping(
        {
            "abstention_reason": "",
            "affected_ir_families": ["deontic"],
            "classification": "missing_semantic_rule",
            "confidence": 0.82,
            "counterexample": {
                "example_id": sample.sample_id,
                "expected_modal_ir_hash": sample.modal_ir.canonical_hash(),
                "source_span_hashes": _source_span_hashes(sample),
                "source_text": sample.text,
                "title": sample.title,
                "section": sample.section,
                "citation": sample.citation,
            },
            "missing_semantic_rule": {"rule_id": "obligation_notice_scope"},
            "proof_obligation_ids": [item.request.proof_obligation_ids[0]],
            "proposed_compiler_surface": [{"component": "deontic.ir"}],
            "request_cache_key": item.request.cache_key,
            "request_id": item.request.request_id,
            "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            "witness": None,
        }
    )
    worker.runner.cache.put(
        item.request,
        response,
        LeanstralAuditValidation(
            accepted=True,
            verified=True,
            cache_key=item.request.cache_key,
            response_hash=response.content_hash,
            verified_by=("test",),
        ),
    )

    verification_records, report = verify_worker_audit_outputs(
        [path],
        worker=worker,
        worker_config=config,
        verifier_config=LeanstralVerifierConfig(
            run_lean=False,
            run_modal_bridge=False,
        ),
    )

    assert verification_records[0]["verification"]["outcome"] == "accepted"
    assert report.gaps[0].status == "accepted"
    assert report.gaps[0].supporting_evidence[0].examples[0]["example_role"] == "counterexample"


def _modal_sample():
    text = "The agency must provide notice within 30 days after application."
    base = build_us_code_sample(title="5", section="552", text=text)
    result = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    ).encode(
        text,
        document_id=base.sample_id,
        citation=base.citation,
        source=base.source,
        source_embedding=base.embedding_vector,
    )
    return replace(
        base,
        modal_ir=result.modal_ir,
        frame_candidates=result.frame_candidates,
        selected_frame=result.selected_frame,
        losses=result.losses,
    )


def _source_span_hashes(sample) -> dict:
    return {
        formula.formula_id: _span_hash(sample, formula)
        for formula in sample.modal_ir.formulas
    }


def _span_hash(sample, formula) -> str:
    import hashlib

    span = sample.normalized_text[
        formula.provenance.start_char : formula.provenance.end_char
    ].strip()
    return hashlib.sha256(span.encode("utf-8")).hexdigest()
