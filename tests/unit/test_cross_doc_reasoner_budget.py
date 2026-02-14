import numpy as np

from ipfs_datasets_py.search.graphrag_integration import (
    CrossDocumentReasoner,
    HybridVectorGraphSearch,
)


class _DenseRelDataset:
    def __init__(self, *, doc_count=10, rels_per_doc=50):
        self._nodes = {}
        self._rels = {}

        # Documents
        for i in range(doc_count):
            doc_id = f"doc{i}"
            self._nodes[doc_id] = {"id": doc_id, "type": "document", "title": doc_id, "content": doc_id}

        # Entities (same entity connected to every doc so it is a connector)
        self._nodes["ent"] = {"id": "ent", "type": "concept", "name": "ent"}

        # Relationships: each doc has many relationships (mostly noise), but at least one to the connector.
        for i in range(doc_count):
            doc_id = f"doc{i}"
            rels = [{"source": doc_id, "target": "ent", "type": "mentions", "weight": 1.0}]
            for j in range(rels_per_doc - 1):
                # Many extra edges to unique throwaway entities.
                eid = f"e{i}_{j}"
                self._nodes[eid] = {"id": eid, "type": "concept", "name": eid}
                rels.append({"source": doc_id, "target": eid, "type": "mentions", "weight": 1.0})
            self._rels[doc_id] = rels

        self._emb = {nid: np.array([1.0, 0.0, 0.0], dtype=np.float32) for nid in self._nodes}

    def search_vectors(self, query_embedding, top_k=10, min_score=0.0):
        # Return docs as seeds
        out = []
        for i in range(min(top_k, 10)):
            out.append({"id": f"doc{i}", "score": 0.9})
        return out

    def get_node(self, node_id):
        return self._nodes[node_id]

    def get_node_relationships(self, node_id):
        return list(self._rels.get(node_id, []))

    def get_node_embedding(self, node_id):
        return self._emb.get(node_id)


def test_cross_doc_respects_edge_scan_cap_and_reports_stats():
    dataset = _DenseRelDataset(doc_count=10, rels_per_doc=50)
    hybrid = HybridVectorGraphSearch(dataset, min_score_threshold=0.0)
    reasoner = CrossDocumentReasoner(dataset, hybrid_search=hybrid, llm_integration=None)

    q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    chains = reasoner.find_evidence_chains(
        query_embedding=q,
        entity_types=["concept"],
        max_docs=10,
        max_entities=5,
        min_doc_score=0.0,
        max_edges_traversed=10,
    )

    stats = reasoner.get_last_query_stats()
    assert "entity_mediated_stats" in stats
    # The scan counter should not exceed the cap by more than 1 due to break condition.
    assert stats["entity_mediated_stats"].get("relationships_scanned", 0) <= 11
    assert stats["max_edges_traversed"] == 10

    # Evidence chains may be empty with such a tight budget, but function should succeed.
    assert isinstance(chains, list)
