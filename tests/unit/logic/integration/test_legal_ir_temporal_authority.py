"""Tests for LegalIR temporal authority and applicability modeling."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    LEGAL_IR_TEMPORAL_AUTHORITY_SCHEMA_VERSION,
    LegalIRCitationGraphBuilder,
    LegalIRTemporalApplicabilityStatus,
    LegalIRTemporalAuthorityGraph,
    LegalIRTemporalAuthorityGraphBuilder,
    LegalIRTemporalChangeKind,
    LegalIRTemporalDiagnosticType,
    LegalIRTemporalQueryContext,
    assert_legal_ir_temporal_authority_applicable,
    build_legal_ir_temporal_authority_graph,
    generate_legal_ir_proof_obligations,
    legal_ir_temporal_authority_allowed_for_use,
    query_legal_ir_temporal_applicability,
    validate_legal_ir_temporal_authority_graph,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_premises import (
    export_legal_ir_premises,
)


def _authority_graph() -> LegalIRTemporalAuthorityGraph:
    builder = LegalIRTemporalAuthorityGraphBuilder(
        temporal_authority_graph_id="temporal-authority-core"
    )
    builder.add_authority(
        "ORS",
        name="Oregon Revised Statutes",
        jurisdiction="OR",
        authority_type="statute",
        hierarchy_rank=80,
        version="2025",
    )
    builder.add_authority(
        "OAR",
        name="Oregon Administrative Rules",
        jurisdiction="OR",
        authority_type="rule",
        hierarchy_rank=40,
        parent_authority_ids=("ORS",),
        version="2025",
        emergency_power=True,
    )
    builder.add_law_version(
        "ORS 192.001",
        law_version_id="law:ors-192-001-v1",
        authority_id="ORS",
        jurisdiction="OR",
        version="2024",
        effective_date="2024-01-01",
        superseded_date="2025-01-01",
        source_node_ids=("node:ors-v1",),
        conclusion_kinds=("obligation",),
    )
    builder.add_law_version(
        "ORS 192.001",
        law_version_id="law:ors-192-001-v2",
        authority_id="ORS",
        jurisdiction="OR",
        version="2025",
        effective_date="2025-01-01",
        sunset_date="2027-01-01",
        source_node_ids=("node:ors-v2",),
        conclusion_kinds=("obligation",),
    )
    builder.add_law_version(
        "OAR 137-001-0001",
        law_version_id="law:oar-emergency",
        authority_id="OAR",
        jurisdiction="OR",
        version="emergency-2025",
        effective_date="2025-02-01",
        emergency=True,
        emergency_expires_on="2025-08-01",
        source_node_ids=("node:oar-emergency",),
        conclusion_kinds=("factual",),
    )
    builder.add_law_version(
        "ORS 192.999",
        law_version_id="law:ors-repealed",
        authority_id="ORS",
        jurisdiction="OR",
        effective_date="2020-01-01",
        source_node_ids=("node:repealed",),
    )
    builder.add_amendment(
        "law:ors-192-001-v1",
        "law:ors-192-001-v2",
        effective_date="2025-01-01",
        change_id="change:amend-192-001",
        authority_id="ORS",
        enacted_date="2024-07-01",
    )
    builder.add_repeal(
        "law:ors-repealed",
        effective_date="2023-06-01",
        change_id="change:repeal-192-999",
        authority_id="ORS",
    )
    return builder.to_temporal_authority_graph()


def test_represents_temporal_lifecycle_and_serializes_stably() -> None:
    graph = _authority_graph()
    rebuilt = LegalIRTemporalAuthorityGraph.from_dict(graph.to_dict())

    assert graph.schema_version == LEGAL_IR_TEMPORAL_AUTHORITY_SCHEMA_VERSION
    assert rebuilt.to_dict() == graph.to_dict()
    assert graph.authority_by_id["OAR"].parent_authority_ids == ("ORS",)
    assert graph.authority_by_id["OAR"].emergency_power
    assert graph.law_version_by_id["law:ors-192-001-v1"].superseded_by == "law:ors-192-001-v2"
    assert graph.law_version_by_id["law:ors-repealed"].repealed_by == "change:repeal-192-999"
    assert graph.change_by_id["change:amend-192-001"].change_kind is LegalIRTemporalChangeKind.AMENDMENT

    validation = validate_legal_ir_temporal_authority_graph(graph)
    assert validation.valid, validation.to_dict()


def test_query_context_selects_correct_version_and_blocks_stale_law() -> None:
    graph = _authority_graph()

    current = query_legal_ir_temporal_applicability(
        graph,
        LegalIRTemporalQueryContext(
            query_date="2025-04-01",
            jurisdiction="OR",
            authority_id="ORS",
            citation="ORS 192.001",
            conclusion_kind="obligation",
        ),
    )

    assert current.proof_safe
    assert current.applicable_law_version_ids == ("law:ors-192-001-v2",)
    assert set(current.excluded_law_version_ids) == {"law:ors-192-001-v1"}
    assert legal_ir_temporal_authority_allowed_for_use(current)
    assert assert_legal_ir_temporal_authority_applicable(current) is current

    stale = query_legal_ir_temporal_applicability(
        graph,
        {
            "query_date": "2025-04-01",
            "jurisdiction": "OR",
            "law_version_ids": ["law:ors-192-001-v1"],
        },
    )

    assert not stale.proof_safe
    assert stale.decisions[0].status is LegalIRTemporalApplicabilityStatus.SUPERSEDED
    assert LegalIRTemporalDiagnosticType.SUPERSEDED_LAW_USED in stale.decisions[0].diagnostic_types
    with pytest.raises(ValueError):
        assert_legal_ir_temporal_authority_applicable(stale)


def test_repeal_sunset_emergency_and_jurisdiction_are_fail_closed() -> None:
    graph = _authority_graph()

    repealed = query_legal_ir_temporal_applicability(
        graph,
        {
            "query_date": "2024-01-01",
            "jurisdiction": "OR",
            "law_version_ids": ["law:ors-repealed"],
        },
    )
    emergency_expired = query_legal_ir_temporal_applicability(
        graph,
        {
            "query_date": "2025-09-01",
            "jurisdiction": "OR",
            "law_version_ids": ["law:oar-emergency"],
            "conclusion_kind": "factual",
        },
    )
    wrong_jurisdiction = query_legal_ir_temporal_applicability(
        graph,
        {
            "query_date": "2025-04-01",
            "jurisdiction": "WA",
            "law_version_ids": ["law:ors-192-001-v2"],
        },
    )
    sunset = query_legal_ir_temporal_applicability(
        graph,
        {
            "query_date": "2027-01-01",
            "jurisdiction": "OR",
            "law_version_ids": ["law:ors-192-001-v2"],
        },
    )

    assert repealed.decisions[0].status is LegalIRTemporalApplicabilityStatus.REPEALED
    assert emergency_expired.decisions[0].status is LegalIRTemporalApplicabilityStatus.EMERGENCY_EXPIRED
    assert wrong_jurisdiction.decisions[0].status is LegalIRTemporalApplicabilityStatus.WRONG_JURISDICTION
    assert sunset.decisions[0].status is LegalIRTemporalApplicabilityStatus.EXPIRED
    assert {issue.code for issue in emergency_expired.diagnostics} == {
        LegalIRTemporalDiagnosticType.EMERGENCY_RULE_EXPIRED.value
    }


def test_authority_hierarchy_preempts_lower_rank_for_same_conflict_key() -> None:
    builder = LegalIRTemporalAuthorityGraphBuilder()
    builder.add_authority("USC", jurisdiction="US", authority_type="statute", hierarchy_rank=100)
    builder.add_authority("CITY", jurisdiction="OR.PORTLAND", authority_type="ordinance", hierarchy_rank=10)
    builder.add_law_version(
        "42 U.S.C. 1983",
        law_version_id="law:federal",
        authority_id="USC",
        jurisdiction="US",
        effective_date="1979-01-01",
        conflict_key="public-record-disclosure",
    )
    builder.add_law_version(
        "PCC 3.96.010",
        law_version_id="law:city",
        authority_id="CITY",
        jurisdiction="OR.PORTLAND",
        effective_date="2020-01-01",
        conflict_key="public-record-disclosure",
    )
    graph = builder.to_temporal_authority_graph()

    result = query_legal_ir_temporal_applicability(
        graph,
        {"query_date": "2025-01-01", "jurisdiction": "OR.PORTLAND"},
    )

    assert result.applicable_law_version_ids == ("law:federal",)
    city = graph.law_version_by_id["law:city"]
    city_decision = next(item for item in result.decisions if item.law_version_id == city.law_version_id)
    assert city_decision.status is LegalIRTemporalApplicabilityStatus.AUTHORITY_PREEMPTED
    assert LegalIRTemporalDiagnosticType.LOWER_AUTHORITY_PREEMPTED in city_decision.diagnostic_types


def test_builds_from_citation_graph_and_document_shapes() -> None:
    citation_builder = LegalIRCitationGraphBuilder(citation_graph_id="citations-temporal")
    citation_builder.add_authority(
        "ORS",
        name="Oregon Revised Statutes",
        jurisdiction="OR",
        authority_type="statute",
        version="2025",
        rank=80,
    )
    citation_builder.add_target(
        "ORS 192.001",
        target_id="target:ors-192-001",
        authority_id="ORS",
        version="2025",
        metadata={
            "effective_date": "2025-01-01",
            "sunset_date": "2026-01-01",
            "law_version_id": "law:from-citation",
        },
    )
    citation_graph = citation_builder.to_citation_graph(resolve=False)
    sample = {
        "sample_id": "sample-temporal",
        "modal_ir": {
            "document_id": "doc-temporal",
            "authority": {
                "authority_id": "OAR",
                "name": "Oregon Administrative Rules",
                "jurisdiction": "OR",
                "rank": 40,
            },
            "law_versions": [
                {
                    "citation": "OAR 137-001-0001",
                    "law_version_id": "law:from-doc",
                    "effective_date": "2025-02-01",
                    "emergency": True,
                    "emergency_expires_on": "2025-08-01",
                }
            ],
        },
    }

    graph = build_legal_ir_temporal_authority_graph(sample, citation_graph=citation_graph)

    assert {"law:from-citation", "law:from-doc"} <= set(graph.law_version_by_id)
    assert graph.authority_by_id["ORS"].hierarchy_rank == 80
    assert graph.law_version_by_id["law:from-doc"].emergency


def test_hammer_obligations_cover_deontic_and_factual_temporal_scope() -> None:
    sample = {
        "sample_id": "sample-obligations",
        "modal_ir": {
            "document_id": "doc-obligations",
            "normalized_text": "The agency shall publish a notice. The report is confidential.",
            "temporal_query_context": {"query_date": "2025-04-01", "jurisdiction": "OR"},
            "authority": {
                "authority_id": "ORS",
                "name": "Oregon Revised Statutes",
                "jurisdiction": "OR",
                "rank": 80,
                "version": "2025",
            },
            "formulas": [
                {
                    "formula_id": "f-deontic",
                    "operator": {"family": "deontic", "system": "KD", "symbol": "shall"},
                    "predicate": {"name": "publish_notice", "arguments": ["agency"], "role": "obligation"},
                    "provenance": {"source_id": "doc-obligations", "citation": "ORS 192.001"},
                    "authority_context": {
                        "citation": "ORS 192.001",
                        "effective_date": "2025-01-01",
                        "conclusion_kind": "obligation",
                    },
                },
                {
                    "formula_id": "f-factual",
                    "operator": {"family": "modal", "system": "K", "symbol": "is"},
                    "predicate": {"name": "confidential_report", "arguments": ["report"], "role": "factual"},
                    "provenance": {"source_id": "doc-obligations", "citation": "ORS 192.002"},
                    "authority_context": {
                        "citation": "ORS 192.002",
                        "effective_date": "2025-01-01",
                        "conclusion_kind": "factual",
                    },
                },
            ],
        },
    }

    obligations = generate_legal_ir_proof_obligations(sample)
    temporal_obligations = [
        obligation for obligation in obligations if obligation.legal_ir_view == "temporal_authority.ir"
    ]
    premises = export_legal_ir_premises(sample, obligations=obligations)

    assert {
        "temporal_authority_deontic_scope",
        "temporal_authority_factual_scope",
    } <= {obligation.kind for obligation in temporal_obligations}
    assert all(
        obligation.metadata["applicability_status"] == "applicable"
        for obligation in temporal_obligations
    )
    assert "date:2025-04-01" in "\n".join(obligation.statement for obligation in temporal_obligations)
    assert any(premise.name == "temporal_authority_window_applies" for premise in premises)
    assert any(premise.name.startswith("temporal_authority_fact_") for premise in premises)
