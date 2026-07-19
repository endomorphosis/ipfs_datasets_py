"""Tests for the Leanstral no-mutation shadow canary."""

from __future__ import annotations

import json
import importlib.util
import hashlib
import sys
import time
from pathlib import Path

from ipfs_datasets_py.logic.modal import (
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LeanstralAuditCache,
    LeanstralAuditResponse,
    LeanstralAuditValidation,
    build_leanstral_audit_work_items,
    validate_leanstral_audit_response,
)

from ipfs_datasets_py.logic.modal import IntrospectionAnalysisConfig, analyze_introspection_disagreements
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[4]
    / "scripts/ops/legal_ir/run_leanstral_shadow_canary.py"
)
_SPEC = importlib.util.spec_from_file_location("run_leanstral_shadow_canary", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_canary = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _canary
_SPEC.loader.exec_module(_canary)

ShadowCanaryConfig = _canary.ShadowCanaryConfig
RealShadowCanaryConfig = _canary.RealShadowCanaryConfig
_build_audit_request = _canary._build_audit_request
_verifier_reference_from_row = _canary._verifier_reference_from_row
build_dry_run_fixture_records = _canary.build_dry_run_fixture_records
discover_latest_disagreement_inputs = _canary.discover_latest_disagreement_inputs
render_markdown_report = _canary.render_markdown_report
resolve_disagreement_input_paths = _canary.resolve_disagreement_input_paths
run_real_shadow_canary = _canary.run_real_shadow_canary
run_shadow_canary = _canary.run_shadow_canary
write_markdown_report = _canary.write_markdown_report


def test_real_shadow_canary_uses_bounded_cached_lean_defaults() -> None:
    verifier = RealShadowCanaryConfig(run_lean=True).verifier_config()

    assert verifier.lean_max_formulas == 12
    assert verifier.lean_parallel_workers == 2
    assert verifier.lean_slice_size == 6
    assert verifier.lean_timeout_seconds == 30.0
    assert verifier.lean_proof_cache_path
    assert verifier.modal_bridge_require_proof is False


def test_real_shadow_canary_passes_provider_fallbacks_and_repair_retries() -> None:
    worker = RealShadowCanaryConfig(
        provider="leanstral_local",
        provider_fallbacks="mistral_vibe",
        validation_repair_retries=2,
    ).worker_config()

    assert worker.provider == "leanstral_local"
    assert worker.provider_fallbacks == "mistral_vibe"
    assert worker.evidence_refresh_policy == "latest_compiler_snapshot"
    assert worker.max_evidence_packets_per_item == 1
    assert worker.validation_repair_retries == 2
    assert worker.provider_candidates() == ("leanstral_local", "mistral_vibe")


def test_latest_disagreement_input_resolves_newest_nonempty_export(tmp_path) -> None:
    older = tmp_path / "older.canonical-disagreements.jsonl"
    newer = tmp_path / "newer.canonical-disagreements.jsonl"
    empty = tmp_path / "empty.canonical-disagreements.jsonl"
    older.write_text("{}\n", encoding="utf-8")
    time.sleep(0.01)
    newer.write_text("{}\n", encoding="utf-8")
    empty.write_text("", encoding="utf-8")

    assert discover_latest_disagreement_inputs(tmp_path) == [str(newer)]


def test_latest_disagreement_input_honors_minimum_record_count(tmp_path) -> None:
    production = tmp_path / "production.canonical-disagreements.jsonl"
    smoke = tmp_path / "smoke.canonical-disagreements.jsonl"
    production.write_text("\n".join("{}" for _ in range(25)) + "\n", encoding="utf-8")
    time.sleep(0.01)
    smoke.write_text("\n".join("{}" for _ in range(4)) + "\n", encoding="utf-8")

    assert discover_latest_disagreement_inputs(tmp_path, min_records=25) == [
        str(production)
    ]
    assert discover_latest_disagreement_inputs(tmp_path, min_records=4) == [
        str(smoke)
    ]


def test_latest_disagreement_input_sentinel_keeps_explicit_paths(tmp_path) -> None:
    packet_path = tmp_path / "packets.canonical-disagreements.jsonl"
    explicit_path = tmp_path / "explicit.jsonl"
    packet_path.write_text("{}\n", encoding="utf-8")

    original_log_dir = _canary.DEFAULT_CANONICAL_PACKET_LOG_DIR
    try:
        _canary.DEFAULT_CANONICAL_PACKET_LOG_DIR = tmp_path
        resolved = resolve_disagreement_input_paths(["latest", explicit_path])
    finally:
        _canary.DEFAULT_CANONICAL_PACKET_LOG_DIR = original_log_dir

    assert resolved == [str(packet_path), str(explicit_path)]


def _records(count: int = 6):
    return build_dry_run_fixture_records(count=count)


def _real_records(count: int = 6):
    records = json.loads(json.dumps(build_dry_run_fixture_records(count=count)))
    for index, record in enumerate(records, start=1):
        sample_id = f"real-canary-sample-{index:03d}"
        record["evidence_id"] = f"real-canary-evidence-{index:03d}"
        record.pop("evidence_provenance", None)
        record["sample_hashes"]["sample_id"] = sample_id
        record["versions"] = {
            "export_schema_version": "legal-ir-introspection-packet-v1",
            "state_version": "canonical-state-v1",
        }
    return records


def _real_packet(
    index: int,
    *,
    state_hash: str = "state-real",
    compiler_commit: str = "commit-real",
    exported_at: float = 1_700_000_000.0,
) -> dict:
    sample_id = f"real-shadow-sample-{index:03d}"
    modal_hash = _canary.canonical_sha256({"modal": sample_id})
    span_hash = _canary.canonical_sha256({"span": sample_id})
    component = (
        "deontic.ir.obligation_scope"
        if index % 2
        else "modal.temporal.deadline_order"
    )
    family = "deontic" if index % 2 else "temporal"
    predicted = "temporal" if family == "deontic" else "deontic"
    return {
        "anti_copy_evidence": {
            "dense_weight_tables_included": False,
            "source_span_copy_ratio": 0.0,
            "stripped_dense_input_key_hashes": [],
        },
        "compiler_decompiler_metrics": {
            "cross_entropy_loss": 0.2 + index * 0.001,
            "cosine_similarity": 0.9,
        },
        "evidence_hashes": {
            "canonical_modal_ir_hash": modal_hash,
            "causal_feature_attribution_hash": _canary.canonical_sha256({"causal": sample_id}),
            "compiler_guidance_hash": _canary.canonical_sha256({"guidance": sample_id}),
            "compiler_metrics_hash": _canary.canonical_sha256({"metrics": sample_id}),
            "learned_view_gaps_hash": _canary.canonical_sha256({"learned": sample_id}),
            "proof_route_hash": _canary.canonical_sha256({"proof": sample_id}),
            "source_span_hashes_hash": _canary.canonical_sha256({"spans": [span_hash]}),
            "state_hash": state_hash,
        },
        "evidence_id": f"real-shadow-evidence-{index:03d}",
        "legal_ir_component_gaps": {component: 0.35 + index * 0.001},
        "legal_ir_views": {
            "canonical": {
                "family_distribution": {family: 1.0},
                "modal_ir_hash": modal_hash,
            },
            "predicted": {
                "family_distribution": {predicted: 0.8},
                "predicted_family": predicted,
                "target_family": family,
            },
        },
        "learned_view_gaps": {family: 0.35 + index * 0.001},
        "proof_route_status": {
            "attempted_count": 1,
            "compiles": True,
            "route_status": "compiled",
            "valid_count": 1,
        },
        "run_context": {
            "compiler_commit": compiler_commit,
            "cycle": index,
            "evaluation_role": "guided" if index % 2 else "unguided",
            "exported_at": exported_at,
            "frozen_canary": {
                "canary_set_hash": "canary-real",
                "enabled": True,
                "index": index,
                "sample_id": sample_id,
            },
            "sample_role": "frozen_canary",
            "state_hash": state_hash,
        },
        "sample_hashes": {
            "modal_ir_hash": modal_hash,
            "normalized_text_hash": _canary.canonical_sha256({"normalized": sample_id}),
            "sample_id": sample_id,
            "source_span_hashes": {"formula": span_hash},
            "source_text_hash": _canary.canonical_sha256({"source": sample_id}),
        },
        "schema_version": "legal-ir-introspection-packet-v1",
    }


def _real_packets(count: int = 25, **kwargs):
    return [_real_packet(index, **kwargs) for index in range(1, count + 1)]


def _verifier_example(text: str = "The agency must provide notice within 30 days after application.") -> dict:
    sample = build_us_code_sample(title="5", section="552", text=text)
    return {
        "citation": sample.citation,
        "example_id": sample.sample_id,
        "expected_modal_ir_hash": sample.modal_ir.canonical_hash(),
        "section": sample.section,
        "source_span_hashes": {
            formula.formula_id: hashlib.sha256(
                sample.normalized_text[
                    formula.provenance.start_char : formula.provenance.end_char
                ]
                .strip()
                .encode("utf-8")
            ).hexdigest()
            for formula in sample.modal_ir.formulas
        },
        "source_text": sample.text,
        "title": sample.title,
    }


def test_verifier_reference_from_row_requires_matching_source_hashes() -> None:
    text = "The agency must provide notice within 30 days after application."
    base = build_us_code_sample(title="5", section="552", text=text)
    packet = {
        "sample_hashes": {
            "modal_ir_hash": base.modal_ir.canonical_hash(),
            "normalized_text_hash": hashlib.sha256(
                base.normalized_text.encode("utf-8")
            ).hexdigest(),
            "sample_id": base.sample_id,
            "source_span_hashes": {},
            "source_text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    }
    row = {
        "title_number": "5",
        "section_number": "552",
        "text": text,
        "normalized_citation": "5 U.S.C. 552",
    }

    reference, failures = _verifier_reference_from_row(packet, row)
    assert failures == ()
    assert reference is not None
    assert reference["example_id"] == base.sample_id
    assert reference["source_text"] == text

    packet["sample_hashes"]["source_text_hash"] = "0" * 64
    reference, failures = _verifier_reference_from_row(packet, row)
    assert reference is None
    assert failures == (f"source_text_hash_mismatch:{base.sample_id}",)


def _seed_verified_real_cache(records, cache_dir: Path, config: RealShadowCanaryConfig):
    worker_config = config.worker_config()
    items, stale = build_leanstral_audit_work_items(records, config=worker_config)
    assert stale == []
    cache = LeanstralAuditCache(cache_dir)
    example = _verifier_example()
    for item in items:
        cluster = item.cluster
        response = LeanstralAuditResponse.from_mapping(
            {
                "abstention_reason": "",
                "affected_ir_families": [cluster.get("semantic_family", "deontic")],
                "classification": "missing_semantic_rule",
                "confidence": 0.84,
                "counterexample": example,
                "missing_semantic_rule": {"rule_id": "real_shadow_rule"},
                "proof_obligation_ids": [item.request.proof_obligation_ids[0]],
                "proposed_compiler_surface": [
                    {"component": cluster.get("compiler_surface", "deontic.ir")}
                ],
                "request_cache_key": item.request.cache_key,
                "request_id": item.request.request_id,
                "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
                "witness": None,
            }
        )
        cache.put(
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
    return items


def test_shadow_canary_dry_run_audits_top_clusters_without_mutation() -> None:
    result = run_shadow_canary(
        _records(8),
        config=ShadowCanaryConfig(dry_run=True, max_clusters=3),
    )

    assert result.selected_cluster_count == 3
    assert result.cache_summary["llm_calls"] == 0
    assert result.cache_summary["requests"] == 3
    assert result.no_mutation["queue_seeded_count"] == 0
    assert result.no_mutation["source_mutation_count"] == 0
    assert result.promotion_allowed is False
    assert "dry_run_no_promotion" in result.promotion_blockers
    assert all(audit.rank <= 3 for audit in result.audits)
    assert result.audits[0].rank_score >= result.audits[-1].rank_score
    assert result.projected_todo_specificity["mean"] > 0.0
    assert result.estimated_compiler_impact["top_promotion_value"] > 0.0
    assert result.evidence_provenance_summary["real_record_count"] == 0
    assert result.evidence_provenance_summary["synthetic_fixture_record_count"] > 0
    assert "no_real_evidence_records" in result.promotion_blockers
    assert "no_provider_or_verified_cache_evidence" in result.promotion_blockers


def test_shadow_canary_report_contains_required_acceptance_sections(tmp_path) -> None:
    result = run_shadow_canary(
        _records(3),
        config=ShadowCanaryConfig(dry_run=True, max_clusters=2),
    )

    report = render_markdown_report(result)
    path = write_markdown_report(result, tmp_path / "shadow.md")

    assert path.read_text(encoding="utf-8") == report
    for section in (
        "## Cache Use",
        "## Evidence Provenance",
        "## Audit Validity",
        "## Theorem Outcomes",
        "## Disagreement Categories",
        "## Projected TODO Specificity",
        "## Estimated Compiler Impact",
        "## No-Mutation Contract",
    ):
        assert section in report
    assert '"schema_version": "legal-ir-leanstral-shadow-canary-v1"' in report


def test_shadow_canary_guardrails_fail_promotion_on_missing_provenance_and_anti_copy() -> None:
    bad_record = {
        "evidence_id": "bad-evidence",
        "heldout_impact_by_surface": {"modal.source_provenance": 0.9},
        "legal_ir_component_gaps": {"modal.source_provenance.span_hash": 0.7},
        "sample_hashes": {"sample_id": "bad-sample"},
    }

    result = run_shadow_canary(
        [bad_record],
        config=ShadowCanaryConfig(dry_run=True, max_clusters=1),
    )

    audit = result.audits[0]
    assert audit.guardrails["provenance"]["passed"] is False
    assert audit.guardrails["anti_copy"]["passed"] is False
    assert "provenance_guardrail_not_satisfied" in result.promotion_blockers
    assert "anti_copy_guardrail_not_satisfied" in result.promotion_blockers


def test_shadow_canary_uses_verified_cache_without_provider_call(tmp_path) -> None:
    records = _real_records(2)
    analysis = analyze_introspection_disagreements(
        records,
        config=IntrospectionAnalysisConfig(max_gaps_per_cluster=50),
    )
    cluster = analysis.clusters[0]
    records_by_evidence_id = {record["evidence_id"]: record for record in records}
    cluster_records = [
        records_by_evidence_id[evidence_id]
        for evidence_id in cluster.evidence_ids
        if evidence_id in records_by_evidence_id
    ]
    request = _build_audit_request(cluster, cluster_records)
    response = LeanstralAuditResponse.from_mapping(
        {
            "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            "request_id": request.request_id,
            "request_cache_key": request.cache_key,
            "classification": "missing_semantic_rule",
            "missing_semantic_rule": {
                "rule_id": "shadow_canary_rule",
                "description": "Audit confirms a report-only compiler gap.",
            },
            "counterexample": {"source_text": "The agency must provide notice."},
            "witness": None,
            "affected_ir_families": [cluster.semantic_family],
            "proposed_compiler_surface": [{"component": cluster.compiler_surface}],
            "confidence": 0.8,
            "proof_obligation_ids": list(request.proof_obligation_ids),
            "abstention_reason": "",
        }
    )
    validation = validate_leanstral_audit_response(request, response)
    assert validation.accepted is True
    cache = LeanstralAuditCache(tmp_path)
    cache.put(request, response, validation)

    result = run_shadow_canary(
        records,
        config=ShadowCanaryConfig(
            dry_run=True,
            max_clusters=1,
            cache_dir=str(tmp_path),
            require_local_verifier=False,
        ),
    )

    assert result.cache_summary["cache_hits"] == 1
    assert result.cache_summary["llm_calls"] == 0
    assert result.audit_validity["verified"] == 1
    assert result.audits[0].audit_verified is True
    assert result.audits[0].evidence_provenance["dominant_kind"] == "cached_real_packet"
    assert result.evidence_provenance_summary["cached_real_packet_count"] > 0
    assert result.evidence_provenance_summary["provider_or_verified_cache_audit_count"] == 1
    assert result.evidence_provenance_summary["real_record_count"] > 0


def test_real_shadow_canary_consumes_25_canonical_packets_with_verified_cache(tmp_path) -> None:
    records = _real_packets(25, exported_at=time.time() - 45.0)
    config = RealShadowCanaryConfig(
        cache_dir=str(tmp_path / "cache"),
        expected_compiler_commit="commit-real",
        expected_state_hash="state-real",
        min_real_packets=25,
        provider_enabled=False,
    )
    items = _seed_verified_real_cache(records, tmp_path / "cache", config)

    result = run_real_shadow_canary(records, config=config)

    assert result.status == "passed", (
        result.blocked_reasons,
        result.verifier_outcomes,
    )
    assert result.valid_real_packet_count == 25
    assert result.invalid_packet_count == 0
    assert result.canonical_state["state_hash"] == "state-real"
    assert result.canonical_state["compiler_commit"] == "commit-real"
    assert result.cache_summary["cache_hits"] == len(items)
    assert result.cache_summary["llm_calls"] == 0
    assert result.audit_validity["verified"] == len(items)
    assert result.verifier_outcomes["accepted"] == len(items)
    assert result.coverage["family_count"] >= 2
    assert result.coverage["surface_count"] >= 2
    assert result.state_to_verified_audit_lag_seconds["count"] == len(items)
    assert result.no_mutation["queue_seeded_count"] == 0
    assert result.no_mutation["source_mutation_count"] == 0
    assert result.synthetic_promotion_evidence_generated is False
    assert result.promotion_allowed is False


def test_real_shadow_canary_limits_audits_without_reducing_packet_validation(tmp_path) -> None:
    records = _real_packets(25)

    result = run_real_shadow_canary(
        records,
        config=RealShadowCanaryConfig(
            cache_dir=str(tmp_path / "cache"),
            max_clusters=1,
            min_real_packets=25,
            provider_enabled=False,
        ),
    )

    assert result.valid_real_packet_count == 25
    assert result.worker_summary["work_item_count"] == 1
    assert result.cache_summary["requests"] == 1
    assert len(result.audits) == 1


def test_real_shadow_canary_selects_latest_snapshot_before_record_cap(tmp_path) -> None:
    older = [
        _real_packet(
            index,
            state_hash="state-old",
            compiler_commit="commit-old",
            exported_at=1_700_000_000.0 + index,
        )
        for index in range(1, 26)
    ]
    newer = [
        _real_packet(
            index + 25,
            state_hash="state-new",
            compiler_commit="commit-new",
            exported_at=1_700_001_000.0 + index,
        )
        for index in range(1, 31)
    ]

    result = run_real_shadow_canary(
        older + newer,
        config=RealShadowCanaryConfig(
            cache_dir=str(tmp_path / "cache"),
            max_records=25,
            min_real_packets=25,
            provider_enabled=False,
        ),
    )

    assert result.valid_real_packet_count == 25
    assert result.canonical_state["state_hash"] == "state-new"
    assert result.canonical_state["compiler_commit"] == "commit-new"
    assert result.canonical_state["snapshot_selection"]["selected_group_packet_count"] == 30
    assert result.canonical_state["snapshot_selection"]["selected_packet_count"] == 25
    assert "canonical_state_not_unique" not in result.blocked_reasons
    assert "compiler_commit_not_unique" not in result.blocked_reasons


def test_real_shadow_canary_reports_insufficient_latest_snapshot_without_mixed_state(
    tmp_path,
) -> None:
    older = [
        _real_packet(
            index,
            state_hash="state-old",
            compiler_commit="commit-old",
            exported_at=1_700_000_000.0 + index,
        )
        for index in range(1, 17)
    ]
    latest = [
        _real_packet(
            index + 16,
            state_hash="state-latest",
            compiler_commit="commit-latest",
            exported_at=1_700_001_000.0 + index,
        )
        for index in range(1, 9)
    ]

    result = run_real_shadow_canary(
        older + latest,
        config=RealShadowCanaryConfig(
            cache_dir=str(tmp_path / "cache"),
            max_records=25,
            min_real_packets=25,
            provider_enabled=False,
        ),
    )

    assert result.valid_real_packet_count == 8
    assert result.canonical_state["state_hash"] == "state-latest"
    assert result.canonical_state["compiler_commit"] == "commit-latest"
    assert result.canonical_state["snapshot_selection"]["selected_group_packet_count"] == 8
    assert "insufficient_real_canonical_packets" in result.blocked_reasons
    assert "canonical_state_not_unique" not in result.blocked_reasons
    assert "compiler_commit_not_unique" not in result.blocked_reasons


def test_real_shadow_canary_prefers_expected_snapshot_in_append_only_export(
    tmp_path,
) -> None:
    expected = [
        _real_packet(
            index,
            state_hash="state-expected",
            compiler_commit="commit-expected",
            exported_at=1_700_000_000.0 + index,
        )
        for index in range(1, 26)
    ]
    latest = [
        _real_packet(
            index + 25,
            state_hash="state-latest",
            compiler_commit="commit-latest",
            exported_at=1_700_001_000.0 + index,
        )
        for index in range(1, 26)
    ]

    result = run_real_shadow_canary(
        expected + latest,
        config=RealShadowCanaryConfig(
            cache_dir=str(tmp_path / "cache"),
            expected_compiler_commit="commit-expected",
            expected_state_hash="state-expected",
            max_records=25,
            min_real_packets=25,
            provider_enabled=False,
        ),
    )

    assert result.valid_real_packet_count == 25
    assert result.invalid_packet_count == 0
    assert result.canonical_state["state_hash"] == "state-expected"
    assert result.canonical_state["compiler_commit"] == "commit-expected"
    assert result.canonical_state["snapshot_selection"]["selection_reason"].startswith(
        "expected_"
    )
    assert "expected_state_hash_mismatch" not in result.blocked_reasons
    assert "expected_compiler_commit_mismatch" not in result.blocked_reasons


def test_real_shadow_canary_blocks_when_leanstral_labs_unavailable(tmp_path) -> None:
    records = _real_packets(25)

    def unavailable_generate(prompt: str, **kwargs: object) -> str:
        raise PermissionError("Leanstral Labs access unavailable")

    result = run_real_shadow_canary(
        records,
        config=RealShadowCanaryConfig(
            cache_dir=str(tmp_path / "cache"),
            min_real_packets=25,
            provider_enabled=True,
            timeout_seconds=2.0,
        ),
        llm_generate=unavailable_generate,
    )

    assert result.status == "blocked"
    assert "leanstral_labs_access_unavailable" in result.blocked_reasons
    assert "no_verified_audit_responses" in result.blocked_reasons
    assert result.cache_summary["unavailable"] > 0
    assert result.synthetic_promotion_evidence_generated is False
    assert result.no_mutation["queue_seeded_count"] == 0


def test_real_shadow_canary_surfaces_worker_timeouts(tmp_path) -> None:
    records = _real_packets(25)

    def slow_generate(prompt: str, **kwargs: object) -> str:
        time.sleep(0.05)
        return "{}"

    result = run_real_shadow_canary(
        records,
        config=RealShadowCanaryConfig(
            cache_dir=str(tmp_path / "cache"),
            max_clusters=1,
            min_real_packets=25,
            provider_enabled=True,
            timeout_seconds=0.001,
        ),
        llm_generate=slow_generate,
    )

    assert result.status == "blocked"
    assert "leanstral_worker_failures" in result.blocked_reasons
    assert "leanstral_worker_timeouts" in result.blocked_reasons
    assert result.cache_summary["failed"] == 1
    assert result.cache_summary["timeouts"] == 1
    assert result.audits[0].status == "timeout"


def test_real_shadow_canary_report_contains_required_acceptance_sections(tmp_path) -> None:
    records = _real_packets(25, exported_at=time.time() - 10.0)
    config = RealShadowCanaryConfig(
        cache_dir=str(tmp_path / "cache"),
        min_real_packets=25,
        provider_enabled=False,
    )
    _seed_verified_real_cache(records, tmp_path / "cache", config)
    result = run_real_shadow_canary(records, config=config)

    report = render_markdown_report(result)
    path = write_markdown_report(result, tmp_path / "real-shadow.md")

    assert path.read_text(encoding="utf-8") == report
    for section in (
        "## Real Packet Validity",
        "## Canonical State And Compiler Commit",
        "## Family And Surface Coverage",
        "## Cache Behavior",
        "## Audit Validity",
        "## Verifier Outcomes",
        "## State-To-Verified-Audit Lag",
        "## No-Mutation Contract",
    ):
        assert section in report
    assert '"schema_version": "legal-ir-leanstral-real-shadow-canary-v1"' in report
    assert "Synthetic promotion evidence generated: `false`" in report


def test_real_shadow_canary_rejects_synthetic_and_mixed_state_packets(tmp_path) -> None:
    records = _real_packets(24)
    synthetic = build_dry_run_fixture_records(count=1)[0]
    records.append(synthetic)
    records[0]["run_context"]["state_hash"] = "state-other"

    result = run_real_shadow_canary(
        records,
        config=RealShadowCanaryConfig(
            cache_dir=str(tmp_path / "cache"),
            expected_state_hash="state-real",
            min_real_packets=25,
            provider_enabled=False,
        ),
    )

    assert result.status == "blocked"
    assert result.valid_real_packet_count < 25
    assert "insufficient_real_canonical_packets" in result.blocked_reasons
    assert "invalid_packets_present" in result.blocked_reasons
    assert result.packet_validity["invalid_reasons"]["synthetic_fixture_not_allowed"] == 1


def test_shadow_canary_result_is_json_ready() -> None:
    result = run_shadow_canary(
        _records(4),
        config=ShadowCanaryConfig(dry_run=True, max_clusters=4),
    )

    encoded = json.dumps(result.to_dict(), sort_keys=True)
    decoded = json.loads(encoded)

    assert decoded["selected_cluster_count"] == 4
    assert decoded["cache_summary"]["requests"] == 4
    assert decoded["evidence_provenance_summary"]["synthetic_fixture_record_count"] > 0
