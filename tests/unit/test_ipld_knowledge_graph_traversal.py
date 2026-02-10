from ipfs_datasets_py.ipld.knowledge_graph import IPLDKnowledgeGraph


def test_traverse_from_entities_with_depths_reports_hops():
    kg = IPLDKnowledgeGraph(name="toy")

    a = kg.add_entity(entity_type="entity", name="A")
    b = kg.add_entity(entity_type="entity", name="B")
    c = kg.add_entity(entity_type="entity", name="C")

    kg.add_relationship("rel", a, b)
    kg.add_relationship("rel", b, c)

    traversed = kg.traverse_from_entities_with_depths([a.id], relationship_types=["rel"], max_depth=2)
    by_name = {e.name: d for e, d in traversed}

    assert by_name["A"] == 0
    assert by_name["B"] == 1
    assert by_name["C"] == 2


def test_traverse_from_entities_respects_max_nodes_visited():
    kg = IPLDKnowledgeGraph(name="toy")

    a = kg.add_entity(entity_type="entity", name="A")
    b = kg.add_entity(entity_type="entity", name="B")
    c = kg.add_entity(entity_type="entity", name="C")

    kg.add_relationship("rel", a, b)
    kg.add_relationship("rel", b, c)

    traversed = kg.traverse_from_entities_with_depths(
        [a.id], relationship_types=["rel"], max_depth=2, max_nodes_visited=2
    )

    names = {e.name for e, _d in traversed}
    # Should include seed and at most one additional node
    assert "A" in names
    assert len(names) <= 2
