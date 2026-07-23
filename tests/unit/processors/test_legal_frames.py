from ipfs_datasets_py.processors.legal_data import FrameKnowledgeBase


def test_frame_knowledge_base_merges_duplicate_values_and_sources():
    kb = FrameKnowledgeBase()
    kb.add_fact("claim:1", "Protected activity", "claim_type", "retaliation", "claim_element")
    kb.add_fact("claim:1", "Protected activity", "claim_type", "retaliation", "review_pass")
    kb.add_fact("claim:1", "Protected activity", "support_ref", "QmEvidence123", "support_trace")

    payload = kb.to_dict()

    assert kb.frame_count() == 1
    assert payload["claim:1"]["name"] == "Protected activity"
    assert payload["claim:1"]["slots"]["claim_type"] == [
        {"value": "retaliation", "sources": ["claim_element", "review_pass"]}
    ]
