from ipfs_datasets_py.processors.legal_data import NeurosymbolicMatcher, build_legal_analysis_bundle


def test_neurosymbolic_matcher_matches_supported_claim():
    from ipfs_datasets_py.processors.legal_data import DependencyGraphBuilder, LegalRequirementsGraphBuilder
    from ipfs_datasets_py.processors.legal_data.case_knowledge import build_case_knowledge_graph

    dependency_graph = DependencyGraphBuilder().build_for_claim("termination", claim_id="claim_1", claim_name="Termination")
    dependency_graph = DependencyGraphBuilder().apply_element_statuses(
        dependency_graph,
        claim_type="termination",
        required_elements=[
            {"element_id": "termination_event", "status": "present", "blocking": True},
            {"element_id": "responsible_actor", "status": "present", "blocking": True},
            {"element_id": "timing_or_reason", "status": "present", "blocking": False},
        ],
    )
    case_graph = build_case_knowledge_graph(
        entities=[
            {"id": "claim_entity", "type": "claim", "label": "Termination"},
            {"id": "doc_1", "type": "evidence", "label": "Termination notice"},
        ],
        relationships=[
            {"id": "rel_1", "source": "claim_entity", "target": "doc_1", "type": "supported_by"},
        ],
    )
    legal_graph = LegalRequirementsGraphBuilder().build_from_statutes(
        [{"name": "Employment Statute", "description": "Covers termination", "text": "Termination requires damages."}],
        ["termination"],
    )

    result = NeurosymbolicMatcher().match_claims_to_law(case_graph, dependency_graph, legal_graph)

    assert result["total_claims"] == 1
    assert result["claims"]
    assert result["claims"][0]["confidence"] >= 0.0


def test_build_legal_analysis_bundle_assembles_normalized_outputs():
    bundle = build_legal_analysis_bundle(
        claim_type="termination",
        claim_label="Termination",
        source_text="Employer fired plaintiff after complaints.",
        canonical_facts=[
            {"text": "Plaintiff was fired.", "fact_type": "impact", "element_tags": ["termination_event"]},
            {"text": "Manager made the decision.", "fact_type": "responsible_party"},
        ],
        document_text=(
            "IN THE UNITED STATES DISTRICT COURT\n\n"
            "Civil Action No. ________________\n\n"
            "PLAINTIFF v. DEFENDANT\n\n"
            "COMPLAINT FOR TERMINATION\n\n"
            "JURISDICTION AND VENUE\n"
            "1. Venue is proper.\n"
            "FACTUAL ALLEGATIONS\n"
            "2. Plaintiff was fired.\n"
            "EVIDENTIARY SUPPORT AND NOTICE\n"
            "COUNT I - TERMINATION\n"
            "PRAYER FOR RELIEF\n"
            "JURY DEMAND\n"
            "SIGNATURE BLOCK\n"
        ),
        case_entities=[
            {"id": "claim_entity", "type": "claim", "label": "Termination"},
            {"id": "person_1", "type": "person", "label": "Plaintiff", "confidence": 0.95},
        ],
        case_relationships=[],
        deontic_statements=[
            {
                "id": "stmt_1",
                "entity": "Employer",
                "modality": "obligation",
                "action": "provide notice",
                "document_source": "Policy",
                "confidence": 0.8,
            }
        ],
        statutes=[
            {"name": "Termination Act", "description": "Termination law", "text": "Termination requires damages."}
        ],
    )

    assert bundle["claim_type"] == "termination"
    assert bundle["dependency_readiness"]["total_claims"] == 1
    assert bundle["document_summary"]["is_formally_valid"] is True
    assert bundle["support_map"]["entry_count"] == 1
    assert "claims" in bundle["neurosymbolic_match"]
