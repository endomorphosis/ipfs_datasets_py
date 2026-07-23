from ipfs_datasets_py.logic.deontic import DeonticGraphBuilder
from ipfs_datasets_py.processors.legal_data import (
    LegalRequirementsGraph,
    LegalRequirementsGraphBuilder,
    SupportMapBuilder,
)


def test_legal_requirements_graph_builder_builds_procedure_graph_and_standard_kg():
    graph = LegalRequirementsGraphBuilder().build_rules_of_procedure("federal")
    kg = graph.to_knowledge_graph()

    assert isinstance(graph, LegalRequirementsGraph)
    assert graph.summary()["total_elements"] >= 4
    assert kg.entities
    assert any(entity.type == "procedural_requirement" for entity in kg.entities)


def test_legal_requirements_graph_builder_builds_statutory_claim_requirements():
    graph = LegalRequirementsGraphBuilder().build_from_statutes(
        [
            {
                "name": "State Contract Act",
                "description": "Creates duties for contract disputes.",
                "citation": "SCA 101",
                "text": "A plaintiff may sue for breach of contract and damages.",
            }
        ],
        ["breach_of_contract"],
    )

    names = {element.name for element in graph.get_elements_by_type("requirement")}
    assert "Valid Contract" in names
    assert "Breach" in names
    assert "Damages" in names


def test_support_map_builder_produces_entries_and_knowledge_graph():
    deontic_graph = DeonticGraphBuilder().build_from_matrix(
        [
            {
                "rule_id": "rule_1",
                "modality": "obligation",
                "predicate": "must preserve records",
                "target_id": "action_records",
                "target_label": "Preserve records",
                "sources": [{"id": "fact:notice", "label": "Notice sent", "node_type": "fact"}],
                "authorities": [{"id": "authority_policy", "label": "Retention Policy"}],
                "active": True,
            }
        ]
    )

    support_map = SupportMapBuilder().build_from_deontic_graph(
        deontic_graph,
        fact_catalog={
            "fact:notice": {
                "predicate": "Notice was sent",
                "status": "supported",
                "source_ids": ["doc_1"],
            }
        },
        filing_map={
            "rule_1": [
                {
                    "filing_id": "complaint_1",
                    "filing_type": "complaint",
                    "proposition": "Defendant had a duty to preserve records",
                }
            ]
        },
    )
    kg = support_map.to_knowledge_graph()

    assert support_map.to_dict()["entry_count"] == 1
    assert any(entity.type == "support_fact" for entity in kg.entities)
    assert any(relationship.type == "SUPPORTED_BY" for relationship in kg.relationships)
