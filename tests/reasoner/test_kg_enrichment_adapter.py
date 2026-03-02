from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_legal_ir import parse_cnl_sentence
from ipfs_datasets_py.processors.legal_data.reasoner.kg_enrichment import (
    apply_kg_enrichment,
    build_kg_drift_assessment,
    build_entity_link_adapter,
    build_relation_enrichment_adapter,
    rollback_kg_enrichment,
)


def test_entity_link_adapter_is_deterministic_and_confidence_scored() -> None:
    ir = parse_cnl_sentence("Company A shall file report within 30 days.", jurisdiction="us/federal")

    out_a = build_entity_link_adapter(ir, kg_namespace="kg", confidence_floor=0.0)
    out_b = build_entity_link_adapter(ir, kg_namespace="kg", confidence_floor=0.0)

    assert out_a == out_b
    assert out_a["summary"]["linked_count"] >= 1
    assert out_a["entity_links"][0]["kg_id"].startswith("kg:entity:")
    assert 0.0 <= out_a["entity_links"][0]["confidence"] <= 0.99


def test_relation_enrichment_adapter_links_frame_roles_to_kg_entities() -> None:
    ir = parse_cnl_sentence("Company A shall file report within 30 days.", jurisdiction="us/federal")
    entity_adapter = build_entity_link_adapter(ir, confidence_floor=0.0)

    rel_adapter = build_relation_enrichment_adapter(ir, entity_adapter, confidence_floor=0.0)

    assert rel_adapter["summary"]["enriched_frame_count"] >= 1
    rel = rel_adapter["relations"][0]
    assert rel["relation_id"].startswith("kg:relation:")
    assert "agent" in rel["role_links"]
    assert rel["role_links"]["agent"]["kg_id"].startswith("kg:entity:")


def test_apply_and_rollback_kg_enrichment_is_reversible() -> None:
    ir = parse_cnl_sentence("Company A shall file report within 30 days.", jurisdiction="us/federal")
    entity_adapter = build_entity_link_adapter(ir, confidence_floor=0.0)
    rel_adapter = build_relation_enrichment_adapter(ir, entity_adapter, confidence_floor=0.0)

    applied = apply_kg_enrichment(ir, entity_adapter, rel_adapter, enable_writes=True)
    enriched_ir = applied["ir"]

    assert set(applied["summary"].keys()) == {"writes_enabled", "entity_writes", "frame_writes"}
    assert applied["summary"]["writes_enabled"] is True
    assert applied["summary"]["entity_writes"] >= 1
    assert applied["summary"]["frame_writes"] >= 1

    entity_ref = next(iter(enriched_ir.entities.keys()))
    frame_ref = next(iter(enriched_ir.frames.keys()))
    assert "kg_link" in enriched_ir.entities[entity_ref].attrs
    assert "kg_role_links" in enriched_ir.frames[frame_ref].attrs

    rolled_back = rollback_kg_enrichment(enriched_ir, applied["rollback"])

    assert "kg_link" not in rolled_back.entities[entity_ref].attrs
    assert "kg_link_confidence" not in rolled_back.entities[entity_ref].attrs
    assert "kg_role_links" not in rolled_back.frames[frame_ref].attrs
    assert "kg_relation_id" not in rolled_back.frames[frame_ref].attrs
    assert "kg_relation_confidence" not in rolled_back.frames[frame_ref].attrs


def test_kg_drift_assessment_passes_for_stable_growth() -> None:
    ir = parse_cnl_sentence("Company A shall file report within 30 days.", jurisdiction="us/federal")
    entity_adapter = build_entity_link_adapter(ir, confidence_floor=0.0)
    rel_adapter = build_relation_enrichment_adapter(ir, entity_adapter, confidence_floor=0.0)

    out = build_kg_drift_assessment(
        baseline_relation_count=1,
        baseline_frame_count=1,
        candidate_relation_adapter=rel_adapter,
        max_relation_growth_factor=2.0,
        max_relations_per_frame=8,
    )

    assert out["summary"]["drift_safe"] is True
    assert out["summary"]["failure_count"] == 0


def test_kg_drift_assessment_fails_for_relation_explosion() -> None:
    synthetic_adapter = {
        "summary": {"frame_count": 2},
        "relations": [
            {"frame_ref": f"frm:{i}", "relation_id": f"kg:relation:{i}", "confidence": 0.9, "role_links": {"agent": {"kg_id": "kg:entity:x", "confidence": 0.9, "entity_ref": "ent:x"}}}
            for i in range(20)
        ],
    }

    out = build_kg_drift_assessment(
        baseline_relation_count=2,
        baseline_frame_count=2,
        candidate_relation_adapter=synthetic_adapter,
        max_relation_growth_factor=2.0,
        max_relations_per_frame=8,
    )

    assert out["summary"]["drift_safe"] is False
    assert out["summary"]["failure_count"] >= 1
    assert any(c["type"] == "relation_growth_factor" and c["passed"] is False for c in out["checks"])
