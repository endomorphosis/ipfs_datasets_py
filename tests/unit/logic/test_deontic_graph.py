from ipfs_datasets_py.logic.deontic import (
    DeonticGraph,
    DeonticGraphBuilder,
    SupportMapBuilder,
)


def test_deontic_graph_builder_supports_round_trip_summary():
    graph = DeonticGraphBuilder().build_from_matrix(
        [
            {
                "rule_id": "rule_1",
                "modality": "obligation",
                "predicate": "must maintain records",
                "target_id": "action_records",
                "target_label": "Maintain records",
                "sources": [
                    {"id": "actor_tenant", "label": "Tenant", "node_type": "actor"},
                    {"id": "condition_monthly", "label": "Monthly", "node_type": "condition"},
                ],
                "authorities": [{"id": "auth_lease", "label": "Lease Agreement"}],
                "active": True,
                "confidence": 0.91,
            }
        ]
    )

    payload = graph.to_dict()
    restored = DeonticGraph.from_dict(payload)

    assert payload["summary"]["total_rules"] == 1
    assert payload["summary"]["node_types"]["actor"] == 1
    assert payload["summary"]["node_types"]["authority"] == 1
    assert restored.summary()["active_modalities"]["obligation"] == 1
    assert restored.rules["rule_1"].target_id == "action_records"


def test_deontic_graph_builder_supports_findings_input():
    graph = DeonticGraphBuilder().build_from_findings(
        [
            {
                "id": "finding_1",
                "modality": "prohibition",
                "action": "Disclose medical records",
                "actors": [{"id": "actor_defendant", "label": "Defendant", "node_type": "actor"}],
                "authorities": [{"id": "auth_statute", "label": "Privacy Statute"}],
                "confidence": 0.88,
            }
        ]
    )

    assert graph.summary()["total_rules"] == 1
    assert graph.summary()["modalities"]["prohibition"] == 1
    assert "auth_statute" in graph.nodes


def test_deontic_graph_reports_conflicts_and_source_gaps():
    graph = DeonticGraphBuilder().build_from_matrix(
        [
            {
                "rule_id": "rule_obligation",
                "modality": "obligation",
                "predicate": "grant_review",
                "target_id": "action_review",
                "target_label": "Grant review",
                "sources": [
                    {"id": "actor_hacc", "label": "HACC", "node_type": "actor", "active": True},
                    {"id": "fact_requested", "label": "Requested", "node_type": "fact", "active": True},
                ],
                "active": True,
            },
            {
                "rule_id": "rule_prohibition",
                "modality": "prohibition",
                "predicate": "grant_review",
                "target_id": "action_review",
                "target_label": "Grant review",
                "sources": [
                    {"id": "actor_hacc", "label": "HACC", "node_type": "actor", "active": True},
                    {"id": "fact_late", "label": "Late", "node_type": "fact", "active": False},
                ],
                "active": True,
            },
        ]
    )

    conflicts = graph.detect_conflicts()
    gap_summary = graph.source_gap_summary()
    rows = graph.export_reasoning_rows()

    assert conflicts[0].modalities == ["obligation", "prohibition"]
    assert gap_summary["fully_supported_rule_count"] == 1
    assert gap_summary["rules_with_gaps"][0]["rule_id"] == "rule_prohibition"
    assert rows[0]["target_label"] == "Grant review"


def test_support_map_builder_creates_rule_centered_support_entries():
    graph = DeonticGraphBuilder().build_from_matrix(
        [
            {
                "rule_id": "rule_1",
                "modality": "obligation",
                "predicate": "grant_review",
                "target_id": "action_review",
                "target_label": "Grant review",
                "sources": [
                    {"id": "fact:request", "label": "Review requested", "node_type": "fact", "active": True},
                    {"id": "fact:notice", "label": "Notice sent", "node_type": "fact", "active": True},
                ],
                "evidence_ids": ["exhibit:A"],
                "active": True,
            }
        ]
    )

    payload = SupportMapBuilder().build_from_deontic_graph(
        graph,
        fact_catalog={
            "fact:request": {"predicate": "requested_review", "status": "verified", "source_ids": ["email:1"]},
            "fact:notice": {"predicate": "sent_notice", "status": "verified", "source_ids": ["notice:1"]},
        },
        filing_map={
            "rule_1": [
                {"filing_id": "motion:show-cause", "filing_type": "motion", "proposition": "Agency had a duty to grant review."}
            ]
        },
    ).to_dict()

    assert payload["entry_count"] == 1
    assert payload["entries"][0]["facts"][0]["fact_id"] == "fact:request"
    assert payload["entries"][0]["filings"][0]["filing_id"] == "motion:show-cause"


def test_deontic_graph_builder_supports_analyzer_style_statements():
    graph = DeonticGraphBuilder().build_from_statements(
        [
            {
                "id": "stmt_1",
                "entity": "Landlord",
                "modality": "obligation",
                "action": "repair the premises",
                "document_source": "Lease",
                "context": "The landlord must repair the premises within seven days.",
                "conditions": ["within seven days"],
                "exceptions": ["unless caused by tenant damage"],
                "confidence": 0.84,
            }
        ]
    )

    assert graph.summary()["total_rules"] == 1
    assert graph.summary()["node_types"]["actor"] == 1
    assert graph.summary()["node_types"]["condition"] == 1
    assert graph.summary()["node_types"]["authority"] == 1
    assert graph.rules["stmt_1"].attributes["document_source"] == "Lease"
