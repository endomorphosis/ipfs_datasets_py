"""Tests for deterministic repairs from verified Legal IR gaps."""

from __future__ import annotations

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_VERIFIED_GAP_REPAIR_SCHEMA_VERSION,
    generate_verified_legal_ir_gap_repairs,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)


def test_verified_gap_repairs_cover_core_legal_ir_views_without_source_copy() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "Except as provided by this subsection, the Agency shall not disclose "
            "records before notice is issued and must file a report within 30 days. "
            "A civil penalty is available as a remedy."
        ),
    )
    guidance = {
        "hammer_guidance_artifacts": [
            {
                "failure_reason": "no_backend_proof",
                "legal_ir_view": "external_provers.router",
                "obligation_id": "obl-external",
                "proof_obligation_ids": ["obl-external"],
                "proved": False,
                "schema_version": "legal-ir-hammer-guidance-v1",
                "trusted": False,
            }
        ]
    }

    repairs = generate_verified_legal_ir_gap_repairs(sample, hammer_guidance=guidance)
    by_family = {repair.gap_family: repair for repair in repairs}

    assert {
        "cec_lifecycle_events",
        "exception_scope_precedence",
        "external_prover_routing",
        "knowledge_graph_role_edges",
        "prohibition_guidance",
        "temporal_deadline",
    }.issubset(by_family)
    assert by_family["prohibition_guidance"].target_component == "deontic.ir"
    assert by_family["prohibition_guidance"].typed_semantics["deontic_operator"] == "F"
    assert by_family["temporal_deadline"].target_component == "TDFOL.prover"
    assert "file" in by_family["cec_lifecycle_events"].typed_semantics[
        "lifecycle_events"
    ]
    assert by_family["knowledge_graph_role_edges"].target_component == (
        "knowledge_graphs.neo4j_compat"
    )
    assert by_family["knowledge_graph_role_edges"].typed_semantics["actor"] == "agency"
    assert by_family["external_prover_routing"].proof_obligation_ids == [
        "obl-external"
    ]
    for repair in repairs:
        payload = repair.to_dict()
        assert payload["schema_version"] == LEGAL_IR_VERIFIED_GAP_REPAIR_SCHEMA_VERSION
        assert payload["allowed_paths"]
        assert payload["target_metrics"]
        assert payload["validation_commands"]
        assert "text" not in payload["typed_semantics"]
        assert payload["metadata"]["source_text_sha256"]
