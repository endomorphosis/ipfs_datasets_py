from ipfs_datasets_py.processors.legal_data import (
    DependencyGraphBuilder,
    build_claim_element_question_text,
    build_proof_lead_question_text,
    match_required_element_id,
    normalize_claim_type,
    refresh_required_elements,
)


def test_claim_intake_helpers_refresh_elements_and_render_questions():
    candidate_claim = {
        "claim_type": "wrongful_termination",
        "label": "Wrongful Termination",
        "description": "Employer fired plaintiff after complaints.",
    }
    canonical_facts = [
        {"text": "Plaintiff was fired on May 1, 2024.", "fact_type": "impact", "element_tags": ["termination_event"]},
        {"text": "Manager issued the decision.", "fact_type": "responsible_party"},
    ]

    elements = refresh_required_elements(candidate_claim, canonical_facts, "The employer fired plaintiff after a complaint.")
    question = build_claim_element_question_text("retaliation", "Retaliation", "causation", "Causation")
    proof_question = build_proof_lead_question_text("employment_discrimination", "Employment Discrimination")

    assert normalize_claim_type("wrongful-termination") == "termination"
    assert any(element["status"] == "present" for element in elements)
    assert "Retaliation" in question
    assert "proof" in proof_question.lower()


def test_match_required_element_and_dependency_graph_readiness():
    matched = match_required_element_id("termination", "We need more detail about the responsible actor and employer.")
    graph = DependencyGraphBuilder().build_for_claim("termination", claim_id="claim_1", claim_name="Termination")
    graph = DependencyGraphBuilder().apply_element_statuses(
        graph,
        claim_type="termination",
        required_elements=[
            {"element_id": "termination_event", "status": "present", "blocking": True},
            {"element_id": "responsible_actor", "status": "present", "blocking": True},
            {"element_id": "timing_or_reason", "status": "missing", "blocking": False},
        ],
    )
    readiness = graph.get_claim_readiness()

    assert matched == "responsible_actor"
    assert readiness["total_claims"] == 1
    assert readiness["ready_count"] == 1
    kg = graph.to_knowledge_graph()
    assert kg.entities
    assert kg.relationships
