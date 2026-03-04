"""Tests for KG enrichment policy: additive-only, counters, and rollback.

Covers issue #1171 (KG Enrichment Policy).
"""
from __future__ import annotations

import copy

import pytest

# Path is set up by the layered conftest.py files (root, tests/, and this directory)
from reasoner.hybrid_v2_blueprint import parse_cnl_to_ir
from reasoner.kg_enrichment import (
    build_entity_link_adapter, apply_kg_enrichment, rollback_kg_enrichment,
    build_relation_enrichment_adapter, build_kg_drift_assessment,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_ir():
    return parse_cnl_to_ir("Contractor shall submit the report")


@pytest.fixture
def enriched(simple_ir):
    entity_adapter = build_entity_link_adapter(simple_ir, kg_namespace="kg", confidence_floor=0.0)
    rel_adapter = build_relation_enrichment_adapter(simple_ir, entity_adapter, confidence_floor=0.0)
    result = apply_kg_enrichment(simple_ir, entity_adapter, rel_adapter, enable_writes=True)
    return simple_ir, result


# ---------------------------------------------------------------------------
# TestKGEnrichmentAdditive
# ---------------------------------------------------------------------------

class TestKGEnrichmentAdditive:
    def test_enrichment_preserves_canonical_ids(self, enriched):
        # GIVEN a freshly parsed IR and an enriched version
        original_ir, enrich_result = enriched
        enriched_ir = enrich_result["ir"]
        # THEN entity canonical IDs are unchanged
        original_ent_ids = set(original_ir.entities.keys())
        enriched_ent_ids = set(enriched_ir.entities.keys())
        assert original_ent_ids == enriched_ent_ids

    def test_enrichment_canonical_id_survives(self, enriched):
        # GIVEN enriched IR
        original_ir, enrich_result = enriched
        enriched_ir = enrich_result["ir"]
        # THEN norm IDs are unchanged
        assert set(original_ir.norms.keys()) == set(enriched_ir.norms.keys())

    def test_enrichment_additive_only(self, enriched):
        # GIVEN original and enriched IRs
        original_ir, enrich_result = enriched
        enriched_ir = enrich_result["ir"]
        # THEN enriched entities have kg_link added (but not in original)
        for ent_id, orig_ent in original_ir.entities.items():
            enriched_ent = enriched_ir.entities[ent_id]
            orig_attrs = set(orig_ent.attrs.keys())
            enriched_attrs = set(enriched_ent.attrs.keys())
            # Enriched should be a superset
            assert orig_attrs <= enriched_attrs
            # New kg attributes are additive
            new_attrs = enriched_attrs - orig_attrs
            assert all("kg" in k for k in new_attrs), (
                f"Non-KG attributes added: {new_attrs}"
            )


# ---------------------------------------------------------------------------
# TestKGEnrichmentCounters
# ---------------------------------------------------------------------------

class TestKGEnrichmentCounters:
    def test_entity_link_adapter_summary_fields(self, simple_ir):
        # GIVEN entity link adapter
        adapter = build_entity_link_adapter(simple_ir, kg_namespace="kg", confidence_floor=0.0)
        summary = adapter["summary"]
        # THEN adapter has required summary fields
        for field in ("candidate_count", "linked_count", "skipped_count"):
            assert field in summary, f"Missing summary field: {field}"

    def test_relation_adapter_summary_fields(self, simple_ir):
        # GIVEN relation enrichment adapter
        entity_adapter = build_entity_link_adapter(simple_ir, kg_namespace="kg", confidence_floor=0.0)
        rel_adapter = build_relation_enrichment_adapter(simple_ir, entity_adapter, confidence_floor=0.0)
        summary = rel_adapter["summary"]
        # THEN adapter has required summary fields
        assert "enriched" in summary or "relations" in rel_adapter

    def test_apply_enrichment_write_summary(self, simple_ir):
        # GIVEN enrichment applied with writes enabled
        entity_adapter = build_entity_link_adapter(simple_ir, kg_namespace="kg", confidence_floor=0.0)
        rel_adapter = build_relation_enrichment_adapter(simple_ir, entity_adapter, confidence_floor=0.0)
        result = apply_kg_enrichment(simple_ir, entity_adapter, rel_adapter, enable_writes=True)
        summary = result["summary"]
        # THEN summary has entity_writes and frame_writes
        assert "entity_writes" in summary
        assert "frame_writes" in summary
        assert summary["entity_writes"] >= 0
        assert summary["frame_writes"] >= 0

    def test_enrichment_report_deterministic(self, simple_ir):
        # GIVEN the same IR enriched twice
        def _enrich(ir):
            ea = build_entity_link_adapter(ir, kg_namespace="kg", confidence_floor=0.0)
            ra = build_relation_enrichment_adapter(ir, ea, confidence_floor=0.0)
            return apply_kg_enrichment(ir, ea, ra, enable_writes=True)

        r1 = _enrich(simple_ir)
        r2 = _enrich(simple_ir)
        # THEN the write counts are the same
        assert r1["summary"]["entity_writes"] == r2["summary"]["entity_writes"]
        assert r1["summary"]["frame_writes"] == r2["summary"]["frame_writes"]


# ---------------------------------------------------------------------------
# TestKGEnrichmentRollback
# ---------------------------------------------------------------------------

class TestKGEnrichmentRollback:
    def test_rollback_removes_only_kg_attrs(self, enriched):
        # GIVEN an enriched IR
        original_ir, enrich_result = enriched
        enriched_ir = enrich_result["ir"]
        rollback_plan = enrich_result["rollback"]
        # WHEN rolled back
        rolled_back = rollback_kg_enrichment(enriched_ir, rollback_plan)
        # THEN kg_link attrs are removed
        for ent in rolled_back.entities.values():
            assert "kg_link" not in ent.attrs, (
                "kg_link should be removed after rollback"
            )

    def test_rollback_is_idempotent(self, enriched):
        # GIVEN an enriched IR
        original_ir, enrich_result = enriched
        enriched_ir = enrich_result["ir"]
        rollback_plan = enrich_result["rollback"]
        # WHEN rolled back twice
        rb1 = rollback_kg_enrichment(enriched_ir, rollback_plan)
        rb2 = rollback_kg_enrichment(rb1, rollback_plan)
        # THEN both produce the same entity attribute sets
        for ent_id in rb1.entities:
            attrs1 = set(rb1.entities[ent_id].attrs.keys())
            attrs2 = set(rb2.entities[ent_id].attrs.keys())
            assert attrs1 == attrs2, (
                f"Entity {ent_id}: rollback not idempotent"
            )

    def test_rollback_restores_previous_values(self, enriched):
        # GIVEN an enriched IR and the original
        original_ir, enrich_result = enriched
        enriched_ir = enrich_result["ir"]
        rollback_plan = enrich_result["rollback"]
        # WHEN rolled back
        rolled_back = rollback_kg_enrichment(enriched_ir, rollback_plan)
        # THEN entity attrs match original (no kg_link in original)
        for ent_id, orig_ent in original_ir.entities.items():
            rb_ent = rolled_back.entities[ent_id]
            orig_label = orig_ent.attrs.get("label")
            rb_label = rb_ent.attrs.get("label")
            assert orig_label == rb_label, (
                f"Entity {ent_id}: label changed after rollback"
            )

    def test_full_cycle_enrich_then_rollback(self, simple_ir):
        # GIVEN a fresh IR
        original_entity_attr_keys = {
            ent_id: set(ent.attrs.keys())
            for ent_id, ent in simple_ir.entities.items()
        }
        # WHEN enriched then rolled back
        entity_adapter = build_entity_link_adapter(simple_ir, kg_namespace="kg", confidence_floor=0.0)
        rel_adapter = build_relation_enrichment_adapter(simple_ir, entity_adapter, confidence_floor=0.0)
        enrich_result = apply_kg_enrichment(simple_ir, entity_adapter, rel_adapter, enable_writes=True)
        enriched_ir = enrich_result["ir"]
        rollback_plan = enrich_result["rollback"]
        rolled_back_ir = rollback_kg_enrichment(enriched_ir, rollback_plan)
        # THEN entity attribute keys match original
        for ent_id, orig_keys in original_entity_attr_keys.items():
            rb_keys = set(rolled_back_ir.entities[ent_id].attrs.keys())
            assert orig_keys == rb_keys, (
                f"Entity {ent_id}: attr keys after full cycle don't match original"
            )
