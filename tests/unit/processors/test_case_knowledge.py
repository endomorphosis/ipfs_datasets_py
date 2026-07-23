from ipfs_datasets_py.processors.legal_data import (
    analyze_case_graph_gaps,
    build_case_knowledge_graph,
    summarize_case_graph,
)


def test_case_knowledge_gap_analysis_finds_missing_timeline_and_support():
    graph = build_case_knowledge_graph(
        entities=[
            {"id": "claim_1", "type": "claim", "label": "Breach of contract", "confidence": 0.95},
            {"id": "person_1", "type": "person", "label": "Jane Doe", "confidence": 0.6},
            {"id": "fact_impact", "type": "fact", "label": "Lost wages", "properties": {"fact_type": "impact"}},
        ],
        relationships=[],
    )

    gaps = analyze_case_graph_gaps(graph)
    gap_types = {gap["type"] for gap in gaps}

    assert "low_confidence_entity" in gap_types
    assert "unsupported_claim" in gap_types
    assert "missing_timeline" in gap_types
    assert "missing_impact_remedy" in gap_types


def test_case_knowledge_summary_reports_graph_statistics():
    graph = build_case_knowledge_graph(
        entities=[
            {"id": "claim_1", "type": "claim", "label": "Privacy claim", "confidence": 0.95},
            {"id": "doc_1", "type": "evidence", "label": "Policy document", "confidence": 0.99},
            {
                "id": "fact_timeline",
                "type": "fact",
                "label": "Termination notice sent May 1, 2024",
                "properties": {"fact_type": "timeline", "event_date_or_range": "2024-05-01"},
                "confidence": 0.9,
            },
        ],
        relationships=[
            {"id": "rel_1", "source": "claim_1", "target": "doc_1", "type": "supported_by"},
            {"id": "rel_2", "source": "claim_1", "target": "fact_timeline", "type": "has_timeline_detail"},
        ],
    )

    summary = summarize_case_graph(graph)

    assert summary["entity_count"] == 3
    assert summary["relationship_count"] == 2
    assert summary["average_confidence"] > 0.9
    assert summary["most_connected_entity"] == "claim_1"
