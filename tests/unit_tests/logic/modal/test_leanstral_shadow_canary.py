"""Tests for the Leanstral no-mutation shadow canary."""

from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

from ipfs_datasets_py.logic.modal import (
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LeanstralAuditCache,
    LeanstralAuditResponse,
    LeanstralAuditValidation,
    validate_leanstral_audit_response,
)

from ipfs_datasets_py.logic.modal import IntrospectionAnalysisConfig, analyze_introspection_disagreements

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
_build_audit_request = _canary._build_audit_request
build_dry_run_fixture_records = _canary.build_dry_run_fixture_records
render_markdown_report = _canary.render_markdown_report
run_shadow_canary = _canary.run_shadow_canary
write_markdown_report = _canary.write_markdown_report


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
