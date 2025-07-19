# Test file for TestQueryEngineInitialization

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os

from tests._test_utils import (
    raise_on_bad_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine

# Check if each classes methods are accessible:
assert QueryEngine.query
assert QueryEngine._normalize_query
assert QueryEngine._detect_query_type
assert QueryEngine._process_entity_query
assert QueryEngine._process_relationship_query
assert QueryEngine._process_semantic_query
assert QueryEngine._process_document_query
assert QueryEngine._process_cross_document_query
assert QueryEngine._process_graph_traversal_query
assert QueryEngine._extract_entity_names_from_query
assert QueryEngine._get_entity_documents
assert QueryEngine._get_relationship_documents
assert QueryEngine._generate_query_suggestions
assert QueryEngine.get_query_analytics


# Check if the modules's imports are accessible:
import asyncio
import logging
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import re

from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, Entity, Relationship


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/tests/ipfs_datasets_py_unit_tests/pdf_processing_/query_engine/test_query_engine_initialization.py

import pytest
import os
from unittest.mock import Mock, patch, MagicMock

from tests._test_utils import (
    raise_on_bad_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine

# Check if each classes methods are accessible:
assert QueryEngine.query
assert QueryEngine._normalize_query
assert QueryEngine._detect_query_type
assert QueryEngine._process_entity_query
assert QueryEngine._process_relationship_query
assert QueryEngine._process_semantic_query
assert QueryEngine._process_document_query
assert QueryEngine._process_cross_document_query
assert QueryEngine._process_graph_traversal_query
assert QueryEngine._extract_entity_names_from_query
assert QueryEngine._get_entity_documents
assert QueryEngine._get_relationship_documents
assert QueryEngine._generate_query_suggestions
assert QueryEngine.get_query_analytics

# Check if the modules's imports are accessible:
import asyncio
import logging
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import re

from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, Entity, Relationship


class TestQueryEngineInitialization:
    """Test QueryEngine initialization and configuration."""

    def test_init_with_valid_graphrag_integrator_only(self):
        """
        GIVEN a valid GraphRAGIntegrator instance
        WHEN QueryEngine is initialized with only the integrator
        THEN expect:
            - Instance created successfully
            - graphrag attribute set to provided integrator
            - storage initialized as new IPLDStorage instance
            - embedding_model loaded as SentenceTransformer with default model
            - query_processors dict contains all expected query types
            - embedding_cache initialized as empty dict
            - query_cache initialized as empty dict
        """
        # GIVEN
        mock_graphrag = Mock(spec=GraphRAGIntegrator)
        
        # Mock SentenceTransformer to avoid actual model loading
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer') as mock_st, \
             patch('ipfs_datasets_py.pdf_processing.query_engine.IPLDStorage') as mock_storage_class:
            
            mock_embedding_model = Mock()
            mock_st.return_value = mock_embedding_model
            mock_storage_instance = Mock(spec=IPLDStorage)
            mock_storage_class.return_value = mock_storage_instance
            
            # WHEN
            engine = QueryEngine(mock_graphrag)
            
            # THEN
            assert engine.graphrag is mock_graphrag
            assert engine.storage is mock_storage_instance
            assert engine.embedding_model is mock_embedding_model
            
            # Check query processors mapping
            expected_processors = {
                'entity_search', 'relationship_search', 'semantic_search',
                'document_search', 'cross_document', 'graph_traversal'
            }
            assert set(engine.query_processors.keys()) == expected_processors
            
            # Check caches are empty
            assert engine.embedding_cache == {}
            assert engine.query_cache == {}
            
            # Verify SentenceTransformer called with default model
            mock_st.assert_called_once_with("sentence-transformers/all-MiniLM-L6-v2")

    def test_init_with_valid_graphrag_and_storage(self):
        """
        GIVEN a valid GraphRAGIntegrator instance
        AND a valid IPLDStorage instance
        WHEN QueryEngine is initialized with both
        THEN expect:
            - Instance created successfully
            - graphrag attribute set to provided integrator
            - storage attribute set to provided storage instance
            - embedding_model loaded with default model
            - All processor methods mapped correctly in query_processors
            - Caches initialized as empty dicts
        """
        # GIVEN
        mock_graphrag = Mock(spec=GraphRAGIntegrator)
        mock_storage = Mock(spec=IPLDStorage)
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer') as mock_st:
            mock_embedding_model = Mock()
            mock_st.return_value = mock_embedding_model
            
            # WHEN
            engine = QueryEngine(mock_graphrag, storage=mock_storage)
            
            # THEN
            assert engine.graphrag is mock_graphrag
            assert engine.storage is mock_storage
            assert engine.embedding_model is mock_embedding_model
            
            # Check all processor methods are mapped
            assert engine.query_processors['entity_search'] == engine._process_entity_query
            assert engine.query_processors['relationship_search'] == engine._process_relationship_query
            assert engine.query_processors['semantic_search'] == engine._process_semantic_query
            assert engine.query_processors['document_search'] == engine._process_document_query
            assert engine.query_processors['cross_document'] == engine._process_cross_document_query
            assert engine.query_processors['graph_traversal'] == engine._process_graph_traversal_query
            
            assert engine.embedding_cache == {}
            assert engine.query_cache == {}

    def test_init_with_custom_embedding_model(self):
        """
        GIVEN a valid GraphRAGIntegrator instance
        AND a custom embedding model name
        WHEN QueryEngine is initialized
        THEN expect:
            - SentenceTransformer loaded with custom model name
            - All other attributes initialized correctly
        """
        # GIVEN
        mock_graphrag = Mock(spec=GraphRAGIntegrator)
        custom_model = "sentence-transformers/paraphrase-MiniLM-L6-v2"
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer') as mock_st, \
             patch('ipfs_datasets_py.pdf_processing.query_engine.IPLDStorage'):
            
            mock_embedding_model = Mock()
            mock_st.return_value = mock_embedding_model
            
            # WHEN
            engine = QueryEngine(mock_graphrag, embedding_model=custom_model)
            
            # THEN
            mock_st.assert_called_once_with(custom_model)
            assert engine.embedding_model is mock_embedding_model

    def test_init_with_invalid_embedding_model_name(self):
        """
        GIVEN a valid GraphRAGIntegrator instance
        AND an invalid embedding model name
        WHEN QueryEngine is initialized
        THEN expect:
            - embedding_model set to None (graceful failure)
            - Warning logged about model loading failure
            - Instance still created successfully
        """
        # GIVEN
        mock_graphrag = Mock(spec=GraphRAGIntegrator)
        invalid_model = "nonexistent/model"
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer') as mock_st, \
             patch('ipfs_datasets_py.pdf_processing.query_engine.IPLDStorage'), \
             patch('ipfs_datasets_py.pdf_processing.query_engine.logger') as mock_logger:
            
            mock_st.side_effect = Exception("Model not found")
            
            # WHEN
            engine = QueryEngine(mock_graphrag, embedding_model=invalid_model)
            
            # THEN
            assert engine.embedding_model is None
            mock_logger.warning.assert_called()
            assert engine.graphrag is mock_graphrag  # Instance still created

    def test_init_with_none_graphrag_integrator(self):
        """
        GIVEN None as graphrag_integrator
        WHEN QueryEngine is initialized
        THEN expect TypeError to be raised
        """
        # GIVEN/WHEN/THEN
        with pytest.raises(TypeError, match="graphrag_integrator cannot be None"):
            QueryEngine(None)

    def test_init_with_invalid_graphrag_integrator_type(self):
        """
        GIVEN an object that is not a GraphRAGIntegrator instance
        WHEN QueryEngine is initialized
        THEN expect TypeError to be raised
        """
        # GIVEN
        invalid_integrator = "not_a_graphrag_integrator"
        
        # WHEN/THEN
        with pytest.raises(TypeError, match="graphrag_integrator must be a GraphRAGIntegrator instance"):
            QueryEngine(invalid_integrator)

    def test_init_with_invalid_storage_type(self):
        """
        GIVEN a valid GraphRAGIntegrator instance
        AND an object that is not an IPLDStorage instance for storage
        WHEN QueryEngine is initialized
        THEN expect TypeError to be raised
        """
        # GIVEN
        mock_graphrag = Mock(spec=GraphRAGIntegrator)
        invalid_storage = "not_a_storage_instance"
        
        # WHEN/THEN
        with pytest.raises(TypeError, match="storage must be an IPLDStorage instance"):
            QueryEngine(mock_graphrag, storage=invalid_storage)

    def test_init_with_empty_embedding_model_string(self):
        """
        GIVEN a valid GraphRAGIntegrator instance
        AND an empty string for embedding_model
        WHEN QueryEngine is initialized
        THEN expect ValueError to be raised
        """
        # GIVEN
        mock_graphrag = Mock(spec=GraphRAGIntegrator)
        empty_model = ""
        
        # WHEN/THEN
        with pytest.raises(ValueError, match="embedding_model cannot be empty"):
            QueryEngine(mock_graphrag, embedding_model=empty_model)

    def test_init_query_processors_mapping_completeness(self):
        """
        GIVEN a valid GraphRAGIntegrator instance
        WHEN QueryEngine is initialized
        THEN expect query_processors dict to contain exactly these keys:
            - 'entity_search'
            - 'relationship_search'
            - 'semantic_search'
            - 'document_search'
            - 'cross_document'
            - 'graph_traversal'
        AND each key maps to the correct method
        """
        # GIVEN
        mock_graphrag = Mock(spec=GraphRAGIntegrator)
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer'), \
             patch('ipfs_datasets_py.pdf_processing.query_engine.IPLDStorage'):
            
            # WHEN
            engine = QueryEngine(mock_graphrag)
            
            # THEN
            expected_mapping = {
                'entity_search': engine._process_entity_query,
                'relationship_search': engine._process_relationship_query,
                'semantic_search': engine._process_semantic_query,
                'document_search': engine._process_document_query,
                'cross_document': engine._process_cross_document_query,
                'graph_traversal': engine._process_graph_traversal_query
            }
            
            assert engine.query_processors == expected_mapping
            assert len(engine.query_processors) == 6

    def test_init_caches_are_empty_dicts(self):
        """
        GIVEN a valid GraphRAGIntegrator instance
        WHEN QueryEngine is initialized
        THEN expect:
            - embedding_cache is an empty dict
            - query_cache is an empty dict
        """
        # GIVEN
        mock_graphrag = Mock(spec=GraphRAGIntegrator)
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer'), \
             patch('ipfs_datasets_py.pdf_processing.query_engine.IPLDStorage'):
            
            # WHEN
            engine = QueryEngine(mock_graphrag)
            
            # THEN
            assert isinstance(engine.embedding_cache, dict)
            assert len(engine.embedding_cache) == 0
            assert isinstance(engine.query_cache, dict)
            assert len(engine.query_cache) == 0

    def test_init_sentence_transformer_import_error(self):
        """
        GIVEN a valid GraphRAGIntegrator instance
        AND SentenceTransformer raises ImportError when instantiated
        WHEN QueryEngine is initialized
        THEN expect:
            - embedding_model set to None
            - ImportError logged but not propagated
            - Instance created successfully
        """
        # GIVEN
        mock_graphrag = Mock(spec=GraphRAGIntegrator)
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer') as mock_st, \
             patch('ipfs_datasets_py.pdf_processing.query_engine.IPLDStorage'), \
             patch('ipfs_datasets_py.pdf_processing.query_engine.logger') as mock_logger:
            
            mock_st.side_effect = ImportError("sentence-transformers not installed")
            
            # WHEN
            engine = QueryEngine(mock_graphrag)
            
            # THEN
            assert engine.embedding_model is None
            mock_logger.error.assert_called()
            assert engine.graphrag is mock_graphrag

    def test_init_with_uninitialized_graphrag_integrator(self):
        """
        GIVEN a GraphRAGIntegrator instance that is not properly initialized
        WHEN QueryEngine is initialized
        THEN expect RuntimeError to be raised
        """
        # GIVEN
        mock_graphrag = Mock(spec=GraphRAGIntegrator)
        mock_graphrag.is_initialized = False  # Assume this attribute indicates initialization status
        
        # WHEN/THEN
        with pytest.raises(RuntimeError, match="GraphRAGIntegrator must be properly initialized"):
            QueryEngine(mock_graphrag)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
