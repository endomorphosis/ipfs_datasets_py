def test_graph_engine_legacy_import_path_points_to_extracted_class():
    from ipfs_datasets_py.knowledge_graphs.core.graph_engine import (
        GraphEngine as ExtractedGraphEngine,
    )
    from ipfs_datasets_py.knowledge_graphs.core.query_executor import (
        GraphEngine as LegacyGraphEngine,
    )

    assert LegacyGraphEngine is ExtractedGraphEngine


def test_knowledge_graph_extraction_legacy_imports_and_wrapper_behavior():
    # Note: the module is imported by the suite's conftest, so we can't
    # reliably assert a DeprecationWarning is emitted here.
    from ipfs_datasets_py.knowledge_graphs import knowledge_graph_extraction

    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

    assert knowledge_graph_extraction.KnowledgeGraph is KnowledgeGraph
    assert hasattr(knowledge_graph_extraction, "KnowledgeGraphExtractorWithValidation")
