"""Tests for the bounded asynchronous Leanstral audit worker."""

from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LeanstralAuditCache,
    LeanstralAuditRequest,
    LeanstralAuditResponse,
    LeanstralAuditRunner,
    LeanstralAuditValidation,
    LeanstralAuditWorkItem,
    LeanstralAuditWorker,
    LeanstralAuditWorkerConfig,
    LeanstralVerifierConfig,
    ModalLogicCodecConfig,
    build_leanstral_audit_work_items,
    load_leanstral_audit_disagreements,
)
from ipfs_datasets_py.logic.modal.leanstral_audit import (
    LEANSTRAL_AUDIT_STOP_TOKENS,
    _leanstral_audit_prompt_payload,
    _leanstral_audit_prompt_text,
    _leanstral_audit_response_format,
    _repair_response_with_grounded_candidate_seed,
    _select_family_balanced_work_items,
    canonical_sha256,
    leanstral_audit_context_preflight,
    normalize_leanstral_audit_response_for_request,
    parse_leanstral_audit_response,
    validate_leanstral_audit_response,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.utils import anyio_compat

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[4]
    / "scripts"
    / "ops"
    / "legal_ir"
    / "run_leanstral_audit_worker.py"
)
_SPEC = importlib.util.spec_from_file_location("run_leanstral_audit_worker", _SCRIPT_PATH)
_audit_worker_script = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _audit_worker_script
_SPEC.loader.exec_module(_audit_worker_script)

load_reference_examples = _audit_worker_script.load_reference_examples
compact_hammer_verification_for_cache = (
    _audit_worker_script.compact_hammer_verification_for_cache
)
parse_args = _audit_worker_script.parse_args
publish_verified_rule_gap_report = _audit_worker_script.publish_verified_rule_gap_report
select_canonical_snapshot_records = _audit_worker_script.select_canonical_snapshot_records
verify_worker_audit_outputs = _audit_worker_script.verify_worker_audit_outputs


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


def _prompt_json_section(prompt: str, section: str) -> dict:
    assert not prompt.lstrip().startswith("{")
    begin = f"BEGIN_{section}_JSON"
    end = f"END_{section}_JSON"
    begin_index = prompt.index(begin) + len(begin)
    end_index = prompt.index(end, begin_index)
    return json.loads(prompt[begin_index:end_index].strip())


def _request_payload_from_prompt(prompt: str) -> dict:
    return _prompt_json_section(prompt, "REQUEST")


def _repair_payload_from_prompt(prompt: str) -> dict:
    return _prompt_json_section(prompt, "VALIDATION_REPAIR")


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


def test_family_balanced_selection_reserves_all_primary_logic_family_slots() -> None:
    request = LeanstralAuditRequest.build(
        evidence={"evidence_id": "family-balance"},
        prompt={"prompt": "audit"},
        model={"model": "Leanstral"},
        proof_obligation_ids=["proof-family-balance"],
    )

    def item(work_key: str, family: str) -> LeanstralAuditWorkItem:
        return LeanstralAuditWorkItem(
            work_key=work_key,
            request=request,
            evidence_ids=(work_key,),
            compiler_commit="commit-a",
            semantic_signature=f"{family}:{work_key}",
            state_hashes=("state-a",),
            source_record_hashes=(work_key,),
            cluster={"semantic_family": family},
        )

    ranked = [
        item("deontic-a", "deontic"),
        item("deontic-b", "deontic"),
        item("tdfol-a", "tdfol"),
        item("dcec-a", "event_calculus"),
        item("flogic-a", "frame_logic"),
        item("kg-a", "graph_projection"),
    ]
    selected = _select_family_balanced_work_items(
        ranked,
        limit=5,
        required_families=(
            "tdfol",
            "dcec",
            "flogic",
            "deontic",
            "knowledge_graph",
        ),
    )

    assert [entry.cluster["semantic_family"] for entry in selected] == [
        "tdfol",
        "event_calculus",
        "frame_logic",
        "deontic",
        "graph_projection",
    ]


def test_live_audit_worker_lean_timeout_default_matches_canary_budget() -> None:
    args = parse_args(["--input", "packets.jsonl"])
    assert args.lean_timeout_seconds == 30.0
    assert args.provider == "leanstral_local"
    assert args.provider_fallbacks == "llama_cpp_native,mistral_vibe"
    assert args.snapshot_selection == "latest_canonical_snapshot"
    assert args.validation_repair_retries == 1
    assert args.max_new_tokens == 1000
    assert args.batch_size == 2
    assert args.batch_max_workers == 2
    assert args.required_semantic_families == (
        "tdfol,dcec,flogic,deontic,knowledge_graph"
    )
    assert args.batch_use_mesh is True
    assert args.prompt_payload_mode == "daemon"
    assert args.context_size_per_slot == 8096
    assert args.context_safety_margin_tokens == 512

    watcher = Path("scripts/ops/legal_ir/watch_leanstral_audit_worker.sh").read_text(
        encoding="utf-8"
    )
    assert "LEANSTRAL_LEAN_TIMEOUT_SECONDS:-30" in watcher
    assert 'DEFAULT_PYTHON_BIN="${ROOT_DIR}/.venv-cuda/bin/python"' in watcher
    assert "LEANSTRAL_AUDIT_PROVIDER:-leanstral_local" in watcher
    assert "LEANSTRAL_AUDIT_PROVIDER_FALLBACKS:-llama_cpp_native,mistral_vibe" in watcher
    assert "IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE:-1" in watcher
    assert "IPFS_DATASETS_PY_LLM_PROVIDER:-ipfs_accelerate_py" in watcher
    assert "IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART:-1" in watcher
    assert "IPFS_ACCELERATE_LLAMA_CPP_PREFETCH_MODEL:-1" in watcher
    assert "IPFS_ACCELERATE_LLAMA_CPP_STARTUP_TIMEOUT_SECONDS:-900" in watcher
    assert "IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE:-${LLAMA_CPP_CONTEXT_DEFAULT}" in watcher
    assert "IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS:-${LLAMA_CPP_GPU_LAYERS_DEFAULT}" in watcher
    assert "IPFS_ACCELERATE_LLAMA_CPP_AUTO_SIZING:-${LLAMA_CPP_AUTO_SIZE_DEFAULT}" in watcher
    assert 'LLAMA_CPP_EXTRA_ARGS_DEFAULT="--parallel ${LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT}"' in watcher
    assert 'LLAMA_CPP_EXTRA_ARGS_DEFAULT="--parallel ${LEANSTRAL_AUDIT_BATCH_SIZE_DEFAULT} --device none --no-op-offload --no-kv-offload"' in watcher
    assert '--context-size "${IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE:-${LLAMA_CPP_CONTEXT_DEFAULT}}"' in watcher
    assert '--gpu-layers "${IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS:-${LLAMA_CPP_GPU_LAYERS_DEFAULT}}"' in watcher
    assert '--extra-args "${IPFS_ACCELERATE_LLAMA_CPP_EXTRA_ARGS:-${LLAMA_CPP_EXTRA_ARGS_DEFAULT}}"' in watcher
    assert "--auto-size" in watcher
    assert "llama_cpp_preflight_if_enabled" in watcher
    assert "ipfs_accelerate_py.utils.llama_cpp" in watcher
    assert "LEANSTRAL_AUDIT_SNAPSHOT_SELECTION:-latest_canonical_snapshot" in watcher
    assert "LEANSTRAL_AUDIT_EXPECTED_COMPILER_COMMIT_AUTO:-1" in watcher
    assert '--expected-compiler-commit "${expected_compiler_commit}"' in watcher
    assert "LEANSTRAL_AUDIT_MIN_SNAPSHOT_RECORDS:-25" in watcher
    assert "LEANSTRAL_AUDIT_VALIDATION_REPAIR_RETRIES:-1" in watcher
    assert "LEANSTRAL_AUDIT_MAX_CONCURRENCY:-1" in watcher
    assert "LEANSTRAL_AUDIT_MAX_RETRIES:-0" in watcher
    assert "LEANSTRAL_AUDIT_TIMEOUT_SECONDS:-600" in watcher
    assert "LEANSTRAL_AUDIT_MAX_WORK_ITEMS:-8" in watcher
    assert "LEANSTRAL_AUDIT_PROVER_PORTFOLIO:-legal_ir_training" in watcher
    assert (
        "LEANSTRAL_AUDIT_REQUIRED_SEMANTIC_FAMILIES:"
        "-tdfol,dcec,flogic,deontic,knowledge_graph"
    ) in watcher
    assert "--family-balanced-selection" in watcher
    assert "LEANSTRAL_AUDIT_MAX_NEW_TOKENS:-1000" in watcher
    assert 'LEANSTRAL_AUDIT_PROMPT_PAYLOAD_MODE:-daemon' in watcher
    assert "--require-exact-token-count" in watcher
    assert "--require-trusted-semantic-context" in watcher
    assert "LEANSTRAL_AUDIT_BATCH_SIZE:-2" in watcher
    assert "LEANSTRAL_AUDIT_BATCH_MAX_WORKERS" in watcher
    assert "LEANSTRAL_AUDIT_BATCH_USE_MESH:-1" in watcher
    assert "--batch-use-mesh" in watcher
    assert 'DEFAULT_INPUT_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}.canonical-disagreements.jsonl"' in watcher
    assert 'LEGACY_INPUT_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.canonical-disagreements.jsonl"' in watcher
    assert 'DEFAULT_REFERENCE_EXAMPLE_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}.reference-examples.json"' in watcher
    assert 'LEGACY_REFERENCE_EXAMPLE_PATH="${ROOT_DIR}/workspace/test-logs/${RUN_ID}-autoencoder.reference-examples.json"' in watcher


def test_hammer_cache_summary_omits_duplicated_premise_graph() -> None:
    payload = {
        "accepted": False,
        "candidate_count": 1,
        "candidate_results": [
            {
                "accepted": False,
                "candidate": {"candidate": "typed_rule(slot)"},
                "candidate_index": 1,
                "hammer_report": {
                    "artifacts": [
                        {
                            "guidance_id": "untrusted-a",
                            "metadata": {"premise_security": {"reports": ["x" * 10_000]}},
                            "trusted": False,
                        }
                    ],
                    "metadata": {
                        "backend_health": {"z3": "unavailable"},
                        "premise_security": {"reports": ["x" * 10_000]},
                    },
                    "obligation_count": 1,
                    "premise_count": 49,
                    "proved_count": 0,
                    "schema_version": "legal-ir-hammer-report-v1",
                    "translation_records": [{"artifact": "x" * 10_000}],
                    "trusted_count": 0,
                },
                "reasons": ["unproved"],
                "trusted": False,
            }
        ],
        "reasons": ["unproved"],
        "schema_version": "legal-ir-leanstral-hammer-verifier-v1",
        "trusted": False,
    }

    compact = compact_hammer_verification_for_cache(payload)
    encoded = json.dumps(compact, sort_keys=True)

    assert len(encoded) < 4_000
    assert "premise_security" not in encoded
    assert "translation_records" not in encoded
    assert "candidate" not in compact["candidate_results"][0]
    assert compact["candidate_results"][0]["hammer_report"]["metadata"][
        "backend_health"
    ] == {"z3": "unavailable"}


def test_provider_candidates_keep_native_and_server_leanstral_attempts() -> None:
    config = LeanstralAuditWorkerConfig(
        provider="mistral_vibe",
        provider_fallbacks="llama_cpp_native,leanstral_local,llama_cpp_native",
    )

    assert config.provider_candidates() == (
        "mistral_vibe",
        "llama_cpp_native",
        "leanstral_local",
    )


def test_worker_config_passes_max_new_tokens_to_runner_config() -> None:
    config = LeanstralAuditWorkerConfig(max_new_tokens=768)

    assert config.runner_config().max_new_tokens == 768


def test_parse_leanstral_audit_response_recovers_fenced_json_with_chat_residue() -> None:
    request = LeanstralAuditRequest.build(
        evidence={"evidence_id": "evidence-a"},
        prompt={"prompt": "audit"},
        model={"model": "Leanstral"},
        proof_obligation_ids=["proof-a"],
    )
    payload = {
        "abstention_reason": "",
        "affected_ir_families": ["deontic"],
        "classification": "missing_semantic_rule",
        "confidence": 0.82,
        "counterexample": {"evidence_id": "evidence-a"},
        "missing_semantic_rule": {"rule_id": "obligation_scope"},
        "proof_obligation_ids": ["proof-a"],
        "proposed_compiler_surface": [{"component": "deontic.ir"}],
        "request_id": request.request_id,
        "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
        "witness": None,
    }
    raw = (
        "```json\n"
        + json.dumps(payload)
        + "\n```<|im_end|>\n<|im_start|>user\n"
        + json.dumps(request.to_dict())
    )

    parsed = parse_leanstral_audit_response(raw)

    assert parsed is not None
    assert parsed.schema_version == LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION
    assert parsed.request_id == request.request_id


def test_normalize_leanstral_response_repairs_request_schema_echo() -> None:
    request = LeanstralAuditRequest.build(
        evidence={"evidence_id": "evidence-a"},
        prompt={"prompt": "audit"},
        model={"model": "Leanstral"},
        proof_obligation_ids=["proof-a"],
    )
    response = LeanstralAuditResponse.from_mapping(
        {
            "abstention_reason": "",
            "affected_ir_families": ["deontic"],
            "classification": "missing_semantic_rule",
            "confidence": 0.82,
            "counterexample": {"evidence_id": "evidence-a"},
            "missing_semantic_rule": {"rule_id": "obligation_scope"},
            "proof_obligation_ids": ["proof-a"],
            "proposed_compiler_surface": [{"component": "deontic.ir"}],
            "request_id": request.request_id,
            "schema_version": request.schema_version,
            "witness": None,
        }
    )

    normalized, reasons = normalize_leanstral_audit_response_for_request(request, response)

    assert normalized is not None
    assert normalized.schema_version == LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION
    assert "normalized_response_schema_version_from_request_context" in reasons
    validation = validate_leanstral_audit_response(
        request,
        normalized,
        verifier_id="unit-test",
    )
    assert validation.accepted


def test_normalize_leanstral_response_fills_request_derived_gap_fields() -> None:
    request = LeanstralAuditRequest.build(
        evidence={
            "cluster": {
                "compiler_surface": "modal.frame_logic",
                "gaps": [
                    {
                        "evidence_id": "evidence-a",
                        "gap_kind": "semantic_family_gap",
                        "metric_name": "frame_logic_family_probability_gap",
                        "predicted_family": "temporal",
                        "semantic_signature": "frame_logic:gap",
                        "target_family": "frame",
                    }
                ],
                "semantic_family": "frame_logic",
                "semantic_signature": "frame_logic:gap",
            }
        },
        prompt={"prompt": "audit"},
        model={"model": "Leanstral"},
        proof_obligation_ids=["proof-a"],
    )
    typo_cache_key = request.cache_key[:32] + "0" + request.cache_key[32:]
    typo_request_id = request.request_id[:-4] + request.request_id[-3:]
    response = LeanstralAuditResponse.from_mapping(
        {
            "abstention_reason": "",
            "affected_ir_families": [],
            "classification": "missing_semantic_rule",
            "confidence": 0.82,
            "counterexample": {"evidence_id": "evidence-a"},
            "missing_semantic_rule": {"description": ""},
            "proof_obligation_ids": ["proof-a"],
            "proposed_compiler_surface": [],
            "request_cache_key": typo_cache_key,
            "request_id": typo_request_id,
            "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            "witness": None,
        }
    )

    normalized, reasons = normalize_leanstral_audit_response_for_request(
        request,
        response,
    )

    assert normalized is not None
    assert normalized.request_id == request.request_id
    assert normalized.request_cache_key == request.cache_key
    assert normalized.affected_ir_families == ("frame_logic",)
    assert normalized.proposed_compiler_surface[0]["component"] == "modal.frame_logic"
    assert normalized.missing_semantic_rule["semantic_signature"] == "frame_logic:gap"
    assert "normalized_request_id_from_request_context" in reasons
    assert "normalized_request_cache_key_from_request_context" in reasons
    assert "filled_proposed_compiler_surface_from_request_context" in reasons
    assert "filled_missing_semantic_rule_from_request_cluster" in reasons
    validation = validate_leanstral_audit_response(
        request,
        normalized,
        verifier_id="unit-test",
    )
    assert validation.accepted


def test_worker_snapshot_selection_uses_latest_coherent_state() -> None:
    older = []
    for index in range(1, 26):
        packet = _packet(index, state_hash="state-old")
        packet["run_context"]["compiler_commit"] = "commit-old"
        packet["run_context"]["exported_at"] = 1_700_000_000.0 + index
        older.append(packet)
    latest = []
    for index in range(26, 34):
        packet = _packet(index, state_hash="state-latest")
        packet["run_context"]["compiler_commit"] = "commit-latest"
        packet["run_context"]["exported_at"] = 1_700_001_000.0 + index
        latest.append(packet)

    selected, metadata = select_canonical_snapshot_records(
        older + latest,
        max_records=25,
        min_records=25,
    )

    assert len(selected) == 8
    assert {record["run_context"]["state_hash"] for record in selected} == {
        "state-latest"
    }
    assert metadata["selected_state_hash"] == "state-latest"
    assert metadata["selected_compiler_commit"] == "commit-latest"
    assert metadata["meets_min_snapshot_records"] is False
    assert metadata["selection_reason"] == "newest_available_snapshot"


def test_worker_snapshot_selection_honors_expected_state_filter() -> None:
    expected = []
    for index in range(1, 4):
        packet = _packet(index, state_hash="state-expected")
        packet["run_context"]["compiler_commit"] = "commit-expected"
        packet["run_context"]["exported_at"] = 1_700_000_000.0 + index
        expected.append(packet)
    latest = []
    for index in range(4, 7):
        packet = _packet(index, state_hash="state-latest")
        packet["run_context"]["compiler_commit"] = "commit-latest"
        packet["run_context"]["exported_at"] = 1_700_001_000.0 + index
        latest.append(packet)

    selected, metadata = select_canonical_snapshot_records(
        expected + latest,
        expected_compiler_commit="commit-expected",
        expected_state_hash="state-expected",
        min_records=3,
    )

    assert len(selected) == 3
    assert {record["run_context"]["state_hash"] for record in selected} == {
        "state-expected"
    }
    assert metadata["selection_reason"] == "expected_newest_min_satisfying_snapshot"


def test_worker_snapshot_selection_rejects_missing_expected_commit() -> None:
    packets = []
    for index in range(1, 4):
        packet = _packet(index, state_hash="state-latest")
        packet["run_context"]["compiler_commit"] = "commit-latest"
        packet["run_context"]["exported_at"] = 1_700_001_000.0 + index
        packets.append(packet)

    selected, metadata = select_canonical_snapshot_records(
        packets,
        expected_compiler_commit="commit-current",
        min_records=1,
    )

    assert selected == []
    assert metadata["expected_filters"] == {"compiler_commit": "commit-current"}
    assert metadata["selected_packet_count"] == 0
    assert metadata["selection_reason"] == "no_matching_snapshot"


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
        assert evidence["owned_compiler_surfaces"]
        assert evidence["referenced_examples"]
        assert evidence["referenced_examples"][0]["compiler_decompiler_metrics"][
            "cross_entropy_loss"
        ] > 0.0
        prompt_payload = item.request.to_prompt_payload()
        assert prompt_payload["audit_response_identity"]["request_id"] == (
            item.request.request_id
        )
        assert prompt_payload["audit_response_identity"]["request_cache_key"] == (
            item.request.cache_key
        )
        assert "Do not copy request.cache_key" in " ".join(
            prompt_payload["instructions"]
        )
        assert prompt_payload["output_contract"]
        assert "modal.ir_decompiler" in prompt_payload["owned_compiler_surfaces"]
        assert prompt_payload["referenced_examples"]
        assert evidence["evidence_packet_selection"] == "ranked_prefix_with_full_hash_manifest"
        assert len(evidence["source_record_hashes"]) == evidence["evidence_packet_count"]
        assert len(evidence["omitted_evidence_packet_hashes"]) == (
            evidence["evidence_packet_count"] - 2
        )
        cluster = evidence["cluster"]
        assert cluster["gap_count"] > len(cluster["gaps"])
        assert len(cluster["gaps"]) <= 2
        assert len(cluster["omitted_gap_hashes"]) == (
            cluster["gap_count"] - len(cluster["gaps"])
        )
        assert cluster["gap_detail_selection"] == (
            "selected_evidence_packets_with_hash_manifest"
        )


def test_worker_builds_hash_attested_semantic_context_and_real_obligations(
    tmp_path,
) -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The agency must provide notice within 30 days after application "
            "unless emergency review applies."
        ),
    )
    packet = _packet(1)
    source_hash = hashlib.sha256(sample.text.encode("utf-8")).hexdigest()
    modal_hash = sample.modal_ir.canonical_hash()
    packet["sample_hashes"].update(
        {
            "modal_ir_hash": modal_hash,
            "sample_id": sample.sample_id,
            "source_text_hash": source_hash,
        }
    )
    packet["evidence_hashes"].update(
        {
            "canonical_modal_ir_hash": modal_hash,
            "source_text_hash": source_hash,
        }
    )
    references = {
        sample.sample_id: {
            "citation": sample.citation,
            "sample_id": sample.sample_id,
            "section": sample.section,
            "text": sample.text,
            "title": sample.title,
        }
    }
    config = LeanstralAuditWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        context_size_per_slot=8096,
        max_work_items=1,
        prompt_payload_mode="daemon",
    )

    item = build_leanstral_audit_work_items(
        [packet],
        config=config,
        reference_examples=references,
    )[0][0]
    context = item.request.evidence["semantic_context"]

    assert context["accepted"] is True
    assert context["legal_text_data"]["value"] == sample.text
    assert context["actual_source_text_hash"] == source_hash
    assert context["actual_modal_ir_hash"] == modal_hash
    assert context["proof_obligations"]
    assert all(
        obligation["obligation_id"].startswith("lir-obligation-")
        for obligation in context["proof_obligations"]
    )
    assert tuple(item.request.proof_obligation_ids) == tuple(
        obligation["obligation_id"]
        for obligation in context["proof_obligations"]
    )
    obligation = context["proof_obligations"][0]
    candidate_contract = item.request.to_prompt_payload()[
        "drafted_logic_candidate_contract"
    ]["proof_obligation_contracts"][0]
    candidate_language = candidate_contract["candidate_language"]
    candidate_text = candidate_language["grounded_candidate_seed"]
    candidate = {
        "candidate": candidate_text,
        "compiler_surface": obligation["legal_ir_view"],
        "confidence": 0.8,
        "contract_id": obligation["metadata"]["contract_id"],
        "expected_failure_mode": "hammer_unproved",
        "logic_family": obligation["logic_family"],
        "premise_hints": obligation["premise_hints"],
        "proof_obligation_ids": [obligation["obligation_id"]],
        "repair_scope": "failed_obligation_subtree",
        "schema_version": "legal-ir-leanstral-hammer-candidate-v1",
        "source_copy_policy": "reject_full_span_copy",
        "source_copy_rejected": False,
        "target_view": obligation["legal_ir_view"],
    }
    response_payload = {
        "abstention_reason": "",
        "affected_ir_families": [obligation["logic_family"]],
        "classification": "missing_semantic_rule",
        "confidence": 0.8,
        "counterexample": {"evidence_id": packet["evidence_id"]},
        "drafted_logic_candidates": [candidate],
        "missing_semantic_rule": {"rule_id": "exception_scope"},
        "proof_obligation_ids": [obligation["obligation_id"]],
        "proposed_compiler_surface": [
            {"component": obligation["legal_ir_view"]}
        ],
        "request_id": item.request.request_id,
        "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
        "witness": None,
    }
    response = LeanstralAuditResponse.from_mapping(response_payload)
    assert validate_leanstral_audit_response(item.request, response).accepted
    copied_obligation = LeanstralAuditResponse.from_mapping(
        {
            **response_payload,
            "drafted_logic_candidates": [
                {
                    **candidate,
                    "candidate": obligation["statement"],
                }
            ],
        }
    )
    copied_obligation_validation = validate_leanstral_audit_response(
        item.request,
        copied_obligation,
    )
    assert copied_obligation_validation.accepted is False
    assert (
        "drafted_logic_candidate_copies_obligation"
        in copied_obligation_validation.reasons
    )
    repair_text = _leanstral_audit_prompt_text(
        item.request,
        payload_mode="daemon",
        repair_attempt=1,
        previous_response_text=json.dumps(copied_obligation.to_dict()),
        previous_validation=copied_obligation_validation,
    )
    candidate_repair = _repair_payload_from_prompt(repair_text)[
        "candidate_repair"
    ]
    assert candidate_repair["allowed_predicate_heads"]
    assert candidate_repair["grounding_symbols"]
    assert candidate_repair["grounded_candidate_seed"] == candidate_text
    assert candidate_repair["minimum_distinct_grounding_symbols"] == 2
    assert candidate_repair["shape_example_only"] == (
        candidate_contract["candidate_language"]["candidate_shape_example"]
    )
    assert (
        "with grounded_candidate_seed exactly"
        in candidate_repair["required_action"]
    )

    untyped = LeanstralAuditResponse.from_mapping(
        {
            **response_payload,
            "drafted_logic_candidates": [
                {**candidate, "candidate": "frame_role_typing"}
            ],
        }
    )
    untyped_validation = validate_leanstral_audit_response(
        item.request,
        untyped,
    )
    assert "untyped_logic" in untyped_validation.reasons
    untyped_repair_text = _leanstral_audit_prompt_text(
        item.request,
        payload_mode="daemon",
        repair_attempt=1,
        previous_response_text=json.dumps(untyped.to_dict()),
        previous_validation=untyped_validation,
    )
    assert (
        _repair_payload_from_prompt(untyped_repair_text)["candidate_repair"][
            "grounded_candidate_seed"
        ]
        == candidate_text
    )
    stubborn_calls = []

    def stubborn_generate(prompt: str, **kwargs: object) -> str:
        stubborn_calls.append(prompt)
        return json.dumps(copied_obligation.to_dict())

    runner = LeanstralAuditRunner(
        config.runner_config(),
        llm_generate=stubborn_generate,
    )
    repaired_result = runner.run(
        evidence=item.request.evidence,
        prompt=item.request.prompt,
        theorem_registry_hash=item.request.theorem_registry_hash,
        proof_obligation_ids=item.request.proof_obligation_ids,
        audit_request=item.request,
    )
    assert repaired_result.generation_attempts == 2
    assert repaired_result.validation.accepted is True
    assert repaired_result.response is not None
    assert (
        repaired_result.response.drafted_logic_candidates[0]["candidate"]
        == candidate_text
    )
    assert (
        "deterministic_grounded_candidate_seed_repair"
        in repaired_result.repair_reasons
    )
    assert len(stubborn_calls) == 2

    direct_repair, direct_repair_applied = (
        _repair_response_with_grounded_candidate_seed(
            item.request,
            copied_obligation,
            copied_obligation_validation,
        )
    )
    assert direct_repair_applied is True
    assert direct_repair.drafted_logic_candidates[0]["candidate"] == candidate_text

    copied = LeanstralAuditResponse.from_mapping(
        {
            **response_payload,
            "drafted_logic_candidates": [
                {**candidate, "candidate": sample.text}
            ],
        }
    )
    copied_validation = validate_leanstral_audit_response(
        item.request,
        copied,
    )
    assert copied_validation.accepted is False
    assert (
        "drafted_logic_candidate_copies_source_span"
        in copied_validation.reasons
    )
    prompt = _leanstral_audit_prompt_text(
        item.request,
        payload_mode="daemon",
    )
    assert sample.text in prompt
    assert "obligation(actor, action) unless exception_condition" not in prompt
    assert "balanced predicate applications" in prompt
    response_format = _leanstral_audit_response_format(item.request)
    response_schema = response_format["json_schema"]["schema"]
    assert response_schema["properties"]["request_id"]["const"] == (
        item.request.request_id
    )
    assert response_schema["properties"]["request_cache_key"]["const"] == (
        item.request.cache_key
    )
    assert response_schema["properties"]["drafted_logic_candidates"][
        "minItems"
    ] == 1
    preflight = leanstral_audit_context_preflight(
        item.request,
        config=config.runner_config(),
    )
    assert preflight["accepted"] is True
    assert preflight["prompt_tokens"] > 0

    too_small = replace(
        config.runner_config(),
        context_size_per_slot=128,
    )
    rejected = leanstral_audit_context_preflight(
        item.request,
        config=too_small,
    )
    assert rejected["accepted"] is False
    assert rejected["reason"] == "context_window_exceeded"


def test_worker_fails_closed_on_reference_source_hash_mismatch(tmp_path) -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency must provide notice.",
    )
    packet = _packet(1)
    packet["sample_hashes"]["sample_id"] = sample.sample_id
    references = {
        sample.sample_id: {
            "sample_id": sample.sample_id,
            "text": sample.text,
            "title": sample.title,
            "section": sample.section,
        }
    }
    config = LeanstralAuditWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        max_work_items=1,
        require_trusted_semantic_context=True,
    )

    item = build_leanstral_audit_work_items(
        [packet],
        config=config,
        reference_examples=references,
    )[0][0]
    context = item.request.evidence["semantic_context"]

    assert context["accepted"] is False
    assert any(
        "source_text_hash_mismatch" in reason
        for reason in context["rejection_reasons"]
    )


def test_daemon_prompt_payload_is_bounded_and_preserves_response_identity(tmp_path) -> None:
    items, stale = build_leanstral_audit_work_items(
        [_packet(index) for index in range(1, 6)],
        config=LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "cache"),
            max_evidence_packets_per_item=1,
            max_work_items=1,
            evidence_refresh_policy="latest_compiler_snapshot",
        ),
    )

    assert stale == []
    request = items[0].request
    full = json.dumps(
        _leanstral_audit_prompt_payload(request, payload_mode="full"),
        ensure_ascii=True,
        sort_keys=True,
    )
    compact = json.dumps(
        _leanstral_audit_prompt_payload(request, payload_mode="compact"),
        ensure_ascii=True,
        sort_keys=True,
    )
    daemon_payload = _leanstral_audit_prompt_payload(request, payload_mode="daemon")
    daemon = json.dumps(daemon_payload, ensure_ascii=True, sort_keys=True)

    assert len(daemon) < len(compact) < len(full)
    assert daemon_payload["request"]["request_id"] == request.request_id
    assert daemon_payload["request"]["cache_key"] == request.cache_key
    assert daemon_payload["response_template"]["request_id"] == request.request_id
    assert daemon_payload["response_template"]["request_cache_key"] == request.cache_key
    assert daemon_payload["response_template"]["proof_obligation_ids"] == [
        request.proof_obligation_ids[0]
    ]
    assert "source_text_excerpt" not in daemon
    daemon_text = _leanstral_audit_prompt_text(request, payload_mode="daemon")
    assert daemon_text.startswith("Leanstral LegalIR audit task.")
    assert not daemon_text.lstrip().startswith("{")
    assert "BEGIN_REQUEST_JSON" in daemon_text
    assert "BEGIN_RESPONSE_TEMPLATE_JSON" in daemon_text
    assert daemon_text.rfind("BEGIN_RESPONSE_TEMPLATE_JSON") > daemon_text.rfind(
        "END_REQUEST_JSON"
    )
    daemon_text_request = _request_payload_from_prompt(daemon_text)
    daemon_text_template = _prompt_json_section(daemon_text, "RESPONSE_TEMPLATE")
    assert daemon_text_request["request_id"] == request.request_id
    assert daemon_text_template["request_id"] == request.request_id
    assert daemon_text_template["request_cache_key"] == request.cache_key
    assert (
        daemon_text_template["schema_version"]
        == LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION
    )
    repair_text = _leanstral_audit_prompt_text(
        request,
        payload_mode="daemon",
        repair_attempt=1,
        previous_response_text='{"schema_version":"bad"}',
        previous_validation=LeanstralAuditValidation(
            accepted=False,
            verified=False,
            reasons=("invalid_json_audit_response",),
            cache_key=request.cache_key,
        ),
    )
    repair = _repair_payload_from_prompt(repair_text)
    assert repair["mode"] == "validation_repair"
    assert repair["validation_reasons"] == ["invalid_json_audit_response"]


def test_latest_compiler_snapshot_stabilizes_requests_until_compiler_changes(
    tmp_path,
) -> None:
    config = LeanstralAuditWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        evidence_refresh_policy="latest_compiler_snapshot",
        max_evidence_packets_per_item=2,
    )
    initial_packets = [_packet(index) for index in range(1, 5)]
    expanded_packets = initial_packets + [_packet(index) for index in range(5, 9)]

    initial_item = build_leanstral_audit_work_items(
        initial_packets,
        config=config,
    )[0][0]
    expanded_item = build_leanstral_audit_work_items(
        expanded_packets,
        config=config,
    )[0][0]

    assert initial_item.request.cache_key == expanded_item.request.cache_key
    assert expanded_item.request.evidence["evidence_packet_count"] == 2
    assert expanded_item.request.evidence["evidence_packet_selection"] == (
        "latest_compiler_stable_snapshot"
    )
    assert "omitted_evidence_packet_hashes" not in expanded_item.request.evidence

    changed_packets = list(initial_packets)
    for index in range(5, 9):
        packet = _packet(index)
        packet["run_context"]["compiler_commit"] = "commit-b"
        changed_packets.append(packet)
    changed_item = build_leanstral_audit_work_items(
        changed_packets,
        config=config,
    )[0][0]

    assert changed_item.compiler_commit == "commit-b"
    assert changed_item.request.cache_key != initial_item.request.cache_key


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
        response_format = kwargs["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True
        assert kwargs["stop"] == list(LEANSTRAL_AUDIT_STOP_TOKENS)
        return _response_json(_request_payload_from_prompt(prompt))

    packets = [_packet(1, component="deontic"), _packet(2, component="temporal")]
    config = LeanstralAuditWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        checkpoint_path=str(tmp_path / "checkpoint.json"),
        max_concurrency=1,
        max_retries=0,
        request_timeout_seconds=2.0,
    )
    worker = LeanstralAuditWorker(config, llm_generate=fake_generate)

    first = anyio_compat.run_with_backend(worker.run_records(packets, source_digest="source-a"))
    second = anyio_compat.run_with_backend(worker.run_records(packets, source_digest="source-a"))

    assert first.completed_count == 2
    assert first.llm_call_count == 2
    assert max_active == 1
    assert (tmp_path / "checkpoint.json").is_file()
    assert second.skipped_checkpoint_count == 2
    assert calls == 2


def test_worker_batches_first_attempt_leanstral_audits(tmp_path) -> None:
    batch_calls = []

    def fake_generate_batch(prompts, **kwargs):
        batch_calls.append((list(prompts), kwargs))
        assert kwargs["allow_local_fallback"] is False
        assert kwargs["disable_model_retry"] is True
        assert kwargs["model_name"] == "Leanstral"
        assert kwargs["provider"] == "leanstral_local"
        response_format = kwargs["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["strict"] is True
        assert kwargs["stop"] == list(LEANSTRAL_AUDIT_STOP_TOKENS)
        return [
            _response_json(_request_payload_from_prompt(prompt))
            for prompt in prompts
        ]

    packets = [_packet(1, component="deontic"), _packet(2, component="temporal")]
    config = LeanstralAuditWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        checkpoint_path=str(tmp_path / "checkpoint.json"),
        max_concurrency=1,
        max_retries=0,
        request_timeout_seconds=2.0,
        batch_size=2,
        batch_max_workers=2,
    )
    worker = LeanstralAuditWorker(config, llm_generate_batch=fake_generate_batch)

    summary = anyio_compat.run_with_backend(worker.run_records(packets, source_digest="source-a"))

    assert summary.completed_count == 2
    assert summary.llm_call_count == 2
    assert [result.status for result in summary.results] == ["accepted", "accepted"]
    # Continuously formed batches are homogeneous by logic family.  These two
    # packets intentionally exercise different families, so each partial batch
    # is flushed independently at end-of-stream.
    assert len(batch_calls) == 2
    assert [len(call[0]) for call in batch_calls] == [1, 1]
    assert all(call[1]["max_workers"] == 2 for call in batch_calls)
    assert all(call[1]["use_mesh"] is True for call in batch_calls)


def test_worker_rechecks_cache_after_provider_disabled_checkpoint(tmp_path) -> None:
    packets = [_packet(1)]
    config = LeanstralAuditWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        checkpoint_path=str(tmp_path / "checkpoint.json"),
        provider_enabled=False,
    )
    first = anyio_compat.run_with_backend(
        LeanstralAuditWorker(config).run_records(packets, source_digest="source-a")
    )
    assert first.results[0].status == "provider_disabled"
    assert first.skipped_checkpoint_count == 0

    item = build_leanstral_audit_work_items(packets, config=config)[0][0]
    response = LeanstralAuditResponse.from_mapping(
        json.loads(
            _response_json(
                {
                    "evidence": item.request.evidence,
                    "model": item.request.model,
                    "prompt": item.request.prompt,
                    "proof_obligation_ids": item.request.proof_obligation_ids,
                    "theorem_registry_hash": item.request.theorem_registry_hash,
                }
            )
        )
    )
    LeanstralAuditCache(tmp_path / "cache").put(
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

    second = anyio_compat.run_with_backend(
        LeanstralAuditWorker(config).run_records(packets, source_digest="source-a")
    )

    assert second.skipped_checkpoint_count == 0
    assert second.cache_hit_count == 1
    assert second.completed_count == 1
    assert second.results[0].status == "cache_hit"
    assert second.audit_policy_report["cached_count"] == 1
    assert second.audit_policy_report["selected_count"] == 0


def test_worker_retries_timeouts_and_reports_labs_unavailable(tmp_path) -> None:
    calls = 0

    def flaky_generate(prompt: str, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient transport failure")
        return _response_json(_request_payload_from_prompt(prompt))

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
    retry_summary = anyio_compat.run_with_backend(retry_worker.run_records([_packet(1)], source_digest="retry"))
    assert retry_summary.completed_count == 1
    assert retry_summary.results[0].attempts == 2

    def unavailable_generate(prompt: str, **kwargs: object) -> str:
        raise PermissionError("Leanstral Labs model access unavailable")

    unavailable_worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "unavailable-cache"),
            max_retries=2,
            provider_fallbacks="",
            request_timeout_seconds=2.0,
        ),
        llm_generate=unavailable_generate,
    )
    unavailable = anyio_compat.run_with_backend(unavailable_worker.run_records([_packet(2)], source_digest="unavailable"))
    assert unavailable.unavailable_count == 1
    assert unavailable.results[0].reasons == ("leanstral_labs_model_unavailable",)

    def oversized_generate(prompt: str, **kwargs: object) -> str:
        raise OSError(errno.E2BIG, "Argument list too long")

    oversized_worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "oversized-cache"),
            max_retries=0,
            provider_fallbacks="",
            request_timeout_seconds=2.0,
        ),
        llm_generate=oversized_generate,
    )
    oversized = anyio_compat.run_with_backend(
        oversized_worker.run_records([_packet(3)], source_digest="oversized")
    )
    assert oversized.failed_count == 1
    assert oversized.results[0].reasons == (
        "provider_error:OSError:argument_list_too_long",
    )


def test_worker_timeout_does_not_late_write_shared_cache(tmp_path) -> None:
    cache_dir = tmp_path / "timeout-cache"

    def slow_generate(prompt: str, **kwargs: object) -> str:
        time.sleep(0.05)
        return _response_json(_request_payload_from_prompt(prompt))

    worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(cache_dir),
            max_concurrency=1,
            max_retries=0,
            request_timeout_seconds=0.01,
            retry_backoff_seconds=0.0,
        ),
        llm_generate=slow_generate,
    )

    summary = anyio_compat.run_with_backend(worker.run_records([_packet(1)], source_digest="timeout"))
    time.sleep(0.1)

    assert summary.failed_count == 1
    assert summary.results[0].status == "timeout"
    assert not list(cache_dir.glob("*.json"))


def test_worker_fails_over_to_explicit_leanstral_provider(tmp_path) -> None:
    providers = []

    def failover_generate(prompt: str, **kwargs: object) -> str:
        providers.append(str(kwargs["provider"]))
        if kwargs["provider"] == "mistral_vibe":
            raise RuntimeError("transient provider failure")
        return _response_json(_request_payload_from_prompt(prompt))

    worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "fallback-cache"),
            max_retries=0,
            provider="mistral_vibe",
            provider_fallbacks="leanstral_local",
            request_timeout_seconds=2.0,
        ),
        llm_generate=failover_generate,
    )

    summary = anyio_compat.run_with_backend(worker.run_records([_packet(1)], source_digest="fallback"))

    assert summary.completed_count == 1
    assert summary.failed_count == 0
    assert summary.results[0].attempts == 2
    assert providers == ["mistral_vibe", "leanstral_local"]


def test_worker_repairs_validation_rejected_audit_response(tmp_path) -> None:
    payloads = []

    def repair_generate(prompt: str, **kwargs: object) -> str:
        request_payload = _request_payload_from_prompt(prompt)
        payloads.append(prompt)
        response = json.loads(_response_json(request_payload))
        if len(payloads) == 1:
            response["counterexample"] = None
            response["proposed_compiler_surface"] = []
            return json.dumps(response)
        repair = _repair_payload_from_prompt(prompt)
        assert repair["mode"] == "validation_repair"
        assert "missing_counterexample_or_witness" in repair["validation_reasons"]
        assert "missing_proposed_compiler_surface" not in repair["validation_reasons"]
        return _response_json(request_payload)

    worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "repair-cache"),
            max_retries=0,
            request_timeout_seconds=2.0,
            validation_repair_retries=1,
        ),
        llm_generate=repair_generate,
    )

    summary = anyio_compat.run_with_backend(worker.run_records([_packet(1)], source_digest="repair"))

    assert summary.completed_count == 1
    assert summary.rejected_count == 0
    assert summary.results[0].attempts == 1
    assert summary.results[0].generation_attempts == 2
    assert "missing_counterexample_or_witness" in summary.results[0].repair_reasons
    assert "filled_proposed_compiler_surface_from_request_context" in summary.results[0].repair_reasons
    assert len(payloads) == 2


def test_worker_normalizes_request_derived_leanstral_envelope_fields(tmp_path) -> None:
    def confused_generate(prompt: str, **kwargs: object) -> str:
        request_payload = _request_payload_from_prompt(prompt)
        response = json.loads(_response_json(request_payload))
        response["request_id"] = request_payload["proof_obligation_ids"][0]
        response["request_cache_key"] = ""
        response["affected_ir_families"] = []
        return json.dumps(response)

    worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "normalize-cache"),
            checkpoint_path=str(tmp_path / "checkpoint.json"),
            max_concurrency=1,
            max_retries=0,
            request_timeout_seconds=2.0,
            validation_repair_retries=0,
        ),
        llm_generate=confused_generate,
    )

    summary = anyio_compat.run_with_backend(worker.run_records([_packet(1)], source_digest="normalize"))

    assert summary.completed_count == 1
    result = summary.results[0]
    assert result.status == "accepted"
    assert result.reasons == ()
    assert "normalized_request_id_from_request_context" in result.repair_reasons
    assert "filled_request_cache_key_from_request_context" in result.repair_reasons
    assert "filled_affected_ir_families_from_request_cluster" in result.repair_reasons


def test_worker_rejects_stale_state_and_non_leanstral_model(tmp_path) -> None:
    stale_worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "cache"),
            expected_state_hash="current-state",
        ),
        llm_generate=lambda prompt, **kwargs: _response_json(_request_payload_from_prompt(prompt)),
    )
    stale = anyio_compat.run_with_backend(stale_worker.run_records([_packet(1, state_hash="old-state")], source_digest="stale"))
    assert stale.work_item_count == 0
    assert stale.stale_state_rejections[0]["reason"] == "stale_state_hash"

    generic_worker = LeanstralAuditWorker(
        LeanstralAuditWorkerConfig(
            cache_dir=str(tmp_path / "generic-cache"),
            model="Mistral-Large",
        ),
        llm_generate=lambda prompt, **kwargs: _response_json(_request_payload_from_prompt(prompt)),
    )
    generic = anyio_compat.run_with_backend(generic_worker.run_records([_packet(2)], source_digest="generic"))
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


def test_worker_publishes_only_nonempty_verified_rule_gap_reports(tmp_path) -> None:
    destination = tmp_path / "canonical.rule-gaps.json"
    useful = {
        "accepted_supporting_audit_count": 2,
        "gaps": [{"gap_id": "gap-a"}],
        "schema_version": "legal-ir-leanstral-rule-gap-report-v1",
        "source_audit_count": 2,
    }

    published = publish_verified_rule_gap_report(destination, useful)
    assert published["status"] == "published"
    stored = json.loads(destination.read_text(encoding="utf-8"))
    assert stored["publication_mode"] == "atomic_nonempty_verified"
    assert stored["report_generated_at"]

    preserved = publish_verified_rule_gap_report(
        destination,
        {
            "accepted_supporting_audit_count": 0,
            "gaps": [],
            "rejected_audits": [
                {"audit_id": "audit-a", "reasons": ["missing_source_text"]},
                {"audit_id": "audit-b", "reasons": ["missing_source_text", "timeout"]},
            ],
            "schema_version": "legal-ir-leanstral-rule-gap-report-v1",
            "source_audit_count": 2,
        },
    )
    assert preserved["status"] == "preserved_existing_nonempty_report"
    assert preserved["latest_rejected_audit_count"] == 2
    assert preserved["latest_rejected_reason_counts"] == {
        "missing_source_text": 2,
        "timeout": 1,
    }
    assert preserved["latest_source_audit_count"] == 2
    assert json.loads(destination.read_text(encoding="utf-8"))["gaps"] == [
        {"gap_id": "gap-a"}
    ]


def test_worker_verifier_resolves_hash_only_audit_from_trusted_examples(tmp_path) -> None:
    sample = _modal_sample()
    packet = _packet(7)
    modal_hash = sample.modal_ir.canonical_hash()
    source_span_hashes = _introspection_source_span_hashes(sample)
    packet["evidence_hashes"]["canonical_modal_ir_hash"] = modal_hash
    packet["legal_ir_views"]["canonical"]["modal_ir_hash"] = modal_hash
    packet["sample_hashes"].update(
        {
            "modal_ir_hash": modal_hash,
            "sample_id": sample.sample_id,
            "source_span_hashes": source_span_hashes,
            "source_text_hash": hashlib.sha256(
                sample.text.encode("utf-8")
            ).hexdigest(),
        }
    )
    packet["evidence_hashes"]["source_text_hash"] = hashlib.sha256(
        sample.text.encode("utf-8")
    ).hexdigest()
    path = tmp_path / "packets.jsonl"
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")
    reference_path = tmp_path / "daemon-state.json"
    reference_path.write_text(
        json.dumps(
            {
                "validation_metric_sample_payloads": [
                    {
                        "citation": sample.citation,
                        "sample_id": sample.sample_id,
                        "section": sample.section,
                        "text": sample.text,
                        "title": sample.title,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    records, failures, _ = load_leanstral_audit_disagreements([path])
    assert failures == []
    config = LeanstralAuditWorkerConfig(
        cache_dir=str(tmp_path / "cache"),
        provider_enabled=False,
    )
    worker = LeanstralAuditWorker(config)
    references = load_reference_examples([reference_path])
    item = build_leanstral_audit_work_items(
        records,
        config=config,
        reference_examples=references,
    )[0][0]
    response = LeanstralAuditResponse.from_mapping(
        {
            "abstention_reason": "",
            "affected_ir_families": ["deontic"],
            "classification": "missing_semantic_rule",
            "confidence": 0.82,
            "counterexample": {
                "evidence_id": packet["evidence_id"],
                "expected": "preserved obligation scope",
                "observed": "lost obligation scope",
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
        reference_examples=references,
        verifier_config=LeanstralVerifierConfig(
            run_lean=False,
            run_modal_bridge=False,
        ),
    )

    assert verification_records[0]["verification"]["outcome"] == "accepted"
    assert verification_records[0]["verification"]["compiler_checks"][0][
        "example_id"
    ] == sample.sample_id
    assert report.gaps[0].status == "accepted"
    assert report.gaps[0].supporting_evidence[0].examples[0]["evidence_id"] == packet[
        "evidence_id"
    ]


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


def _introspection_source_span_hashes(sample) -> dict:
    hashes = {}
    for formula in sample.modal_ir.formulas:
        start = formula.provenance.start_char
        end = formula.provenance.end_char
        span_text_hash = hashlib.sha256(sample.text[start:end].encode("utf-8")).hexdigest()
        hashes[formula.formula_id] = canonical_sha256(
            {
                "end_char": end,
                "formula_id": formula.formula_id,
                "span_text_hash": span_text_hash,
                "start_char": start,
            }
        )
    return hashes


def _span_hash(sample, formula) -> str:
    import hashlib

    span = sample.normalized_text[
        formula.provenance.start_char : formula.provenance.end_char
    ].strip()
    return hashlib.sha256(span.encode("utf-8")).hexdigest()
